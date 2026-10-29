import json
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from education.models import Course, Lesson
from ai.test_quiz_protocol import generated, question
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
        self.body = {
            "action": "generate", "lesson": self.lesson.pk, "niveau": "tronc_commun",
            "description": "PRIVATE_SENTINEL : calcul numérique", "question_count": 1,
            "generation_id": str(self.identifier), "resource_selection_present": "1",
        }
        self.progress = reverse("quizzes:generation_progress", args=[self.identifier])

    def login(self, user):
        session = self.client.session
        session["user_id"] = user.pk
        session.save()

    def generate(self):
        with patch("ai.services.AIService.generate_quiz_from_lesson",
                   return_value=json.loads(generated(question()))):
            return self.client.post(reverse("quizzes:teacher_ai"), self.body)

    def test_correlated_summary_is_private_and_records_render_and_persistence(self):
        with self.assertLogs("ai.quiz_metrics", level="INFO") as logs:
            response = self.generate()
        self.assertEqual(response.headers["X-Quiz-Generation-ID"], str(self.identifier))
        self.assertIn("quiz;dur=", response.headers["Server-Timing"])
        run = QuizGenerationRun.objects.get(pk=self.identifier)
        self.assertEqual(run.state, "complete")
        self.assertEqual(run.quiz_id, Quiz.objects.get().pk)
        self.assertIn("render", run.metrics["phases_ms"])
        self.assertIn("persistence", run.metrics["phases_ms"])
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(run.metrics))
        self.assertNotIn("PRIVATE_SENTINEL", "\n".join(logs.output))

    def test_duplicate_post_cannot_generate_or_save_twice(self):
        self.generate()
        with patch("ai.services.AIService.generate_quiz_from_lesson") as generation:
            response = self.client.post(reverse("quizzes:teacher_ai"), self.body)
        self.assertEqual(response.status_code, 409)
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
        self.body["generation_id"] = str(uuid.uuid4())
        self.generate()
        self.assertEqual(QuizGenerationRun.objects.count(), 1)
        self.assertEqual(Quiz.objects.count(), 2)

    def test_failed_validation_marks_run_failed_and_saves_no_quiz(self):
        self.body["lesson"] = ""
        self.client.post(reverse("quizzes:teacher_ai"), self.body)
        self.assertEqual(QuizGenerationRun.objects.get().state, "failed")
        self.assertFalse(Quiz.objects.exists())
