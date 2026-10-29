import json
import shutil
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from accounts.models import User, TeacherProfile
from education.models import Course, Lesson
from education.media_library import chapter_relative
from quizzes.models import Quiz, QuizGenerationQuestion, QuizGenerationRun
from ai.services import AIService
from ai.test_quiz_protocol import ANALYSIS, SECOND, question, generated, reviews


@override_settings(QUIZ_SEMANTIC_CHECK_ENABLED=False)
class QuizProtocolBrowserTests(StaticLiveServerTestCase):
    def test_teacher_runs_full_protocol_with_sources_then_without_files(self):
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            teacher = User.objects.create_user(
                username="protocol-browser", email="protocol-browser@example.test",
                password="Browser-test-only-123!", role="teacher",
            )
            TeacherProfile.objects.get_or_create(user=teacher)
            course = Course.objects.create(name="Mathématiques", niveau="tronc_commun")
            lesson = Lesson.objects.create(course=course, title="Calculs et équations", order=1)
            folder = Path(directory) / chapter_relative(lesson) / "Sources_IA"
            folder.mkdir(parents=True)
            example = "Résoudre $2x=10$."
            (folder / "Calculs.txt").write_text("SOURCE_SELECTED\n" + example, encoding="utf-8")
            (folder / "Autre.txt").write_text("SOURCE_NOT_SELECTED", encoding="utf-8")
            stages, generation_count = [], 0
            def response(messages, **kwargs):
                nonlocal generation_count
                system = messages[0]["content"]
                if "ÉTAPE 1" in system:
                    stages.append("analysis")
                    context = json.loads(messages[1]["content"])["context"]
                    source = "\n".join(part["text"] for part in json.loads(messages[1]["content"])["source_segments"])
                    self.assertNotIn("SOURCE_NOT_SELECTED", source)
                    if source:
                        self.assertIn("SOURCE_SELECTED", source)
                        self.assertIn("UPLOADED_GUIDANCE", source)
                    return json.dumps({**ANALYSIS, "reference_questions": [example] if source else []})
                if "ÉTAPE 4" in system:
                    stages.append("review")
                    time.sleep(0.8)
                    payload = json.loads(messages[1]["content"])
                    self.assertNotIn("is_correct", json.dumps(payload["questions"]))
                    return reviews()
                if "Tu contrôles la diversité" in system:
                    stages.append("diversity")
                    return '{"similar_questions":[]}'
                stages.append("generation")
                generation_count += 1
                return generated(question() if generation_count == 1 else SECOND)
            with sync_playwright() as pw, patch.object(AIService, "_chat", side_effect=response):
                browser = pw.chromium.launch(
                    executable_path=shutil.which("chromium"), headless=True, args=["--no-sandbox"],
                )
                try:
                    page = browser.new_page(viewport={"width": 1280, "height": 1000})
                    page.goto(self.live_server_url + reverse("accounts:login"))
                    page.locator('[name="email"]').fill(teacher.email)
                    page.locator('[name="password"]').fill("Browser-test-only-123!")
                    page.get_by_role("button", name="Se connecter", exact=True).click()
                    page.wait_for_url(self.live_server_url + reverse("accounts:dashboard"))
                    page.goto(self.live_server_url + reverse("quizzes:teacher_ai"))
                    page.select_option("#niveauSelect", "tronc_commun")
                    page.select_option("#lessonSelect", str(lesson.pk))
                    page.locator("#questionCount").fill("1")
                    page.locator("#quizDescription").fill("Calculs et équations : varier les raisonnements.")
                    page.select_option("#sourceFileSelect", "Calculs.txt")
                    page.locator("#quizResourceUploads").set_input_files({
                        "name": "Objectifs.txt", "mimeType": "text/plain",
                        "buffer": b"UPLOADED_GUIDANCE : calculs et situations concretes.",
                    })
                    with page.expect_response(lambda r: r.request.method == "POST" and "/suivi/" in r.url):
                        with page.expect_response(lambda r: r.request.method == "POST" and "/generer-envoyer/" in r.url):
                            page.locator("#genBtn").click()
                            expect(page.locator("#genBtn")).to_be_disabled()
                            expect(page.locator("[data-gen-status]")).to_contain_text("Vérification mathématique")
                            page.locator("#genForm").evaluate("(form) => form.requestSubmit()")
                    report = page.get_by_role("status").filter(has_text="Analyse pédagogique effectuée")
                    expect(report).to_be_visible()
                    expect(report).to_contain_text("ne constitue pas une preuve mathématique générale")
                    expect(report).to_contain_text("Le contrôle de répétition des questions est désactivé.")
                    expect(page.locator(".qb-detail-explain")).to_contain_text("cinq")
                    report.scroll_into_view_if_needed()
                    page.screenshot(path="/tmp/quiz-protocol-desktop.jpg")
                    page.set_viewport_size({"width": 390, "height": 1000})
                    report.scroll_into_view_if_needed()
                    self.assertTrue(page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"))
                    page.screenshot(path="/tmp/quiz-protocol-mobile.jpg")
                    page.select_option("#generationMode", "topic")
                    page.locator("#quizSubject").fill("Calcul numérique et situations concrètes")
                    with page.expect_response(lambda r: r.request.method == "POST" and "/suivi/" in r.url):
                        with page.expect_response(lambda r: r.request.method == "POST" and "/generer-envoyer/" in r.url):
                            page.locator("#genBtn").click()
                    expect(page.locator(".qb-detail-explain")).to_contain_text("douze")
                    expect(page.get_by_role("status").filter(has_text="Analyse pédagogique effectuée")).to_be_visible()
                    self.assertEqual(stages, ["analysis", "generation", "review"] * 2)
                finally:
                    browser.close()
            self.assertEqual(Quiz.objects.count(), 2)
            self.assertEqual(QuizGenerationQuestion.objects.count(), 0)
            runs = list(QuizGenerationRun.objects.order_by("created_at"))
            self.assertEqual(len(runs), 2)
            self.assertTrue(all(run.state == "complete" for run in runs))
            self.assertTrue(all(run.metrics["browser"]["dom_ready_ms"] >=
                                run.metrics["browser"]["html_received_ms"] for run in runs))
