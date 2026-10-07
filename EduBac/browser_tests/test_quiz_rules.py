"""Real-session regression: quiz results → empty board → rule, shared renderer."""
import json
import os
import shutil
from unittest.mock import patch

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from django.utils import timezone
from playwright.sync_api import expect, sync_playwright

from accounts.models import StudentProfile, TeacherProfile, User
from education.models import Course, Lesson
from quizzes.models import Attempt, Question, Quiz, StudentAnswer
from whiteboard.models import QuizCorrectionBoard


class QuizRuleBrowserTests(StaticLiveServerTestCase):
    def test_rule_only_replaces_steps_and_matches_generate_explanation(self):
        # All ORM work precedes the synchronous Playwright runtime.
        teacher = User.objects.create_user(
            username="rule-teacher", email="rule-teacher@example.test",
            password="Browser-test-only-123!", role="teacher",
        )
        TeacherProfile.objects.get_or_create(user=teacher)
        student = User.objects.create_user(
            username="rule-student", email="rule-student@example.test",
            password="Browser-test-only-123!", role="student",
        )
        StudentProfile.objects.get_or_create(user=student, defaults={"niveau": "tronc_commun"})
        course = Course.objects.create(name="Algèbre", niveau="tronc_commun")
        lesson = Lesson.objects.create(course=course, title="Identités", content="Identités remarquables")
        rule_text = "Identité remarquable\n$$(a+b)^2 = a^2 + 2ab + b^2$$"
        quiz = Quiz.objects.create(title="Quiz de règle", lesson=lesson, created_by=teacher)
        question = Question.objects.create(
            quiz=quiz, text="Développer $(x+3)^2$", correct_answer="$x^2+6x+9$",
            explanation=rule_text + "\nÉtape 1 : remplacer b par 3.",
        )
        attempt = Attempt.objects.create(
            student=student, quiz=quiz, submitted_at=timezone.now(), score=100,
        )
        StudentAnswer.objects.create(
            attempt=attempt, question=question, answer="$x^2+6x+9$", is_correct=True,
        )
        QuizCorrectionBoard.objects.create(
            attempt=attempt, question=question,
            data={"version": 1, "title": "Correction", "connections": [],
                  "elements": [{"id": f"step{i}", "type": "step", "text": f"Ancienne étape {i}"}
                               for i in range(1, 6)]},
        )
        board_path = f"/tableau/correction/{attempt.pk}/{question.pk}/"
        preview = {
            "title": "Quiz prévisualisé",
            "questions": [{"text": "Développer $(a+b)^2$", "explanation": rule_text,
                           "choices": [{"text": "$a^2+2ab+b^2$", "is_correct": True}]}],
        }
        rule = {"name": "Identité remarquable", "statement": "",
                "latex": r"(a+b)^2 = a^2 + 2ab + b^2"}
        with patch("ai.services.AIService.generate_quiz_from_lesson", return_value=preview), \
                patch("ai.services.AIService._chat", return_value=json.dumps(rule)), \
                sync_playwright() as pw:
            browser = pw.chromium.launch(
                executable_path=os.environ.get("CHROMIUM_EXECUTABLE") or shutil.which("chromium"),
                headless=True, args=["--no-sandbox"],
            )
            try:
                teacher_page = browser.new_page()
                # Use the project's configured login URL, not an auth bypass.
                teacher_page.goto(self.live_server_url + reverse("accounts:login"))
                teacher_page.locator('input[name="email"]').fill(teacher.email)
                teacher_page.locator('input[name="password"]').fill("Browser-test-only-123!")
                teacher_page.get_by_role("button", name="Se connecter", exact=True).click()
                teacher_page.wait_for_url(lambda url: "/connexion/" not in url)
                teacher_page.goto(self.live_server_url + "/quizzes/generer-envoyer/")
                teacher_page.locator('select[name="niveau"]').select_option("tronc_commun")
                teacher_page.locator('select[name="lesson"]').select_option(str(lesson.pk))
                teacher_page.locator('button[name="action"][value="generate"]').click()
                expected = teacher_page.locator(".qb-detail-explain .katex")
                expect(expected).to_have_count(1)
                generate_math = expected.evaluate("(node) => node.outerHTML")

                context = browser.new_context(viewport={"width": 1280, "height": 900})
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(self.live_server_url + reverse("accounts:login"))
                page.locator('input[name="email"]').fill(student.email)
                page.locator('input[name="password"]').fill("Browser-test-only-123!")
                page.get_by_role("button", name="Se connecter", exact=True).click()
                page.wait_for_url(lambda url: "/connexion/" not in url)
                page.goto(self.live_server_url + f"/quizzes/tentative/{attempt.pk}/resultats/")
                page.locator(f'a[href="{board_path}"]').click()
                expect(page.locator("#qwbCanvas .qwb-el")).to_have_count(1)
                math = page.locator("#qwbCanvas .katex")
                expect(math).to_have_count(1)
                self.assertEqual(math.evaluate("(node) => node.outerHTML"), generate_math)
                expect(page.locator("#qwbCanvas")).not_to_contain_text("Étape")
                expect(page.locator("#qwbCanvas")).not_to_contain_text("Ancienne")
                expect(page.locator("#qwbCanvas")).not_to_contain_text("x^2+6x+9")
                expect(page.locator("#qwbChat")).not_to_be_visible()
                page.keyboard.press("Control+z")
                page.keyboard.press("Control+y")
                expect(page.locator("#qwbCanvas .qwb-el")).to_have_count(1)
                # A subsequent opening also removes student edits/old snapshots.
                page.locator("#qwbCanvas .qwb-el").click()
                page.locator("#qwbEditText").fill("Ancien contenu ajouté manuellement")
                page.locator("#qwbEditText").dispatch_event("change")
                expect(page.locator("#qwbStatus")).to_have_text("Enregistré")
                page.reload()
                expect(page.locator("#qwbCanvas .katex")).to_have_count(1)
                expect(page.locator("#qwbCanvas")).not_to_contain_text("Ancien contenu")
                screenshot_dir = os.environ.get("QUIZ_RULE_SCREENSHOT_DIR")
                if screenshot_dir:
                    page.screenshot(path=os.path.join(screenshot_dir, "quiz-rule-desktop.png"))
                page.set_viewport_size({"width": 390, "height": 844})
                page.wait_for_function(
                    "document.getElementById('edubacSidebar').getBoundingClientRect().right <= 1"
                )
                expect(page.locator("#qwbCanvas .katex")).to_be_visible()
                if screenshot_dir:
                    page.screenshot(path=os.path.join(screenshot_dir, "quiz-rule-mobile.png"))
                self.assertEqual(errors, [])
            finally:
                browser.close()
