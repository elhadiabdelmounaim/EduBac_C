import json
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from education.models import Course, Lesson
from .models import Quiz, QuizGenerationRun


@override_settings(ALLOWED_HOSTS=["testserver"])
class GenerationPerformanceTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username="perf-owner", email="perf-owner@example.test", role="teacher",
        )
        self.other = User.objects.create_user(
            username="perf-other", email="perf-other@example.test", role="teacher",
        )
        self.lesson = Lesson.objects.create(
            title="Calculs", course=Course.objects.create(name="Mathématiques", niveau="tronc_commun"),
        )
        self.login(self.teacher)
        self.identifier = uuid.uuid4()
        self.document = {
            "quiz": {
                "title": "PRIVATE_SENTINEL : calcul numérique",
                "level": "tronc_commun",
                "lesson": "Calculs",
                "duration": 10,
                "questions": [{
                    "id": "Q1", "type": "multiple_choice",
                    "statement": "Calculer $2+2$.", "correct_answer": "A",
                    "difficulty": "easy", "points": 1,
                    "choices": [
                        {"id": "A", "text": "4"}, {"id": "B", "text": "3"},
                        {"id": "C", "text": "5"}, {"id": "D", "text": "6"},
                    ],
                }],
            },
        }
        self.progress = reverse("quizzes:generation_progress", args=[self.identifier])

    def login(self, user):
        session = self.client.session
        session["user_id"] = user.pk
        session.save()

    def generate(self):
        return self.client.post(reverse("quizzes:teacher_ai"), {
            "action": "import_json",
            "niveau": self.lesson.course.niveau,
            "course": self.lesson.course_id,
            "lesson": self.lesson.pk,
            "seconds_per_question": "30",
            "generation_id": str(self.identifier),
            "quiz_json": SimpleUploadedFile(
                "quiz.json", json.dumps(self.document, ensure_ascii=False).encode(),
                content_type="application/json",
            ),
        })

    def test_import_trace_is_private_and_does_not_call_the_ai_provider(self):
        with patch("ai.services.AIService.generate_quiz_from_lesson") as ai_call, \
                self.assertLogs("ai.quiz_metrics", level="INFO") as logs:
            response = self.generate()
        self.assertEqual(response.headers["X-Quiz-Generation-ID"], str(self.identifier))
        self.assertIn("quiz;dur=", response.headers["Server-Timing"])
        run = QuizGenerationRun.objects.get(pk=self.identifier)
        self.assertEqual(run.state, "complete")
        self.assertEqual(run.quiz_id, Quiz.objects.get().pk)
        self.assertEqual(run.metrics["phases_ms"], {})
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(run.metrics))
        self.assertNotIn("PRIVATE_SENTINEL", "\n".join(logs.output))
        ai_call.assert_not_called()

    def test_duplicate_post_cannot_generate_or_save_twice(self):
        self.generate()
        with patch("ai.services.AIService.generate_quiz_from_lesson") as generation:
            response = self.generate()
        self.assertRedirects(response, reverse("quizzes:teacher_ai"), fetch_redirect_response=False)
        generation.assert_not_called()
        self.assertEqual(Quiz.objects.count(), 1)

    def test_progress_only_visible_to_owner_and_never_exposes_questions(self):
        self.generate()
        response = self.client.get(self.progress)
        self.assertEqual(response.json()["state"], "complete")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertNotIn("questions", response.json())
        self.login(self.other)
        self.assertEqual(self.client.get(self.progress).status_code, 404)

    def test_numeric_browser_metrics_are_recorded_without_accepting_content(self):
        self.generate()
        values = {"http_headers_ms": 20.5, "html_received_ms": 30, "dom_ready_ms": 50}
        response = self.client.post(self.progress, json.dumps(values), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(QuizGenerationRun.objects.get().metrics["browser"], values)
        for invalid in ({"dom_ready_ms": -1}, {"prompt": "private"}, {"dom_ready_ms": True},
                        {"dom_ready_ms": float("inf")}, ["private"]):
            response = self.client.post(self.progress, json.dumps(invalid), content_type="application/json")
            self.assertEqual(response.status_code, 400)

    def test_expired_progress_disappears_without_deleting_quiz(self):
        self.generate()
        QuizGenerationRun.objects.update(created_at=timezone.now() - timedelta(days=2))
        self.assertEqual(self.client.get(self.progress).status_code, 404)
        self.identifier = uuid.uuid4()
        self.progress = reverse("quizzes:generation_progress", args=[self.identifier])
        self.generate()
        self.assertEqual(QuizGenerationRun.objects.count(), 1)
        self.assertEqual(Quiz.objects.count(), 2)

    def test_failed_validation_marks_run_failed_and_saves_no_quiz(self):
        self.document["quiz"]["questions"][0]["correct_answer"] = "Z"
        self.generate()
        self.assertEqual(QuizGenerationRun.objects.get().state, "failed")
        self.assertFalse(Quiz.objects.exists())
