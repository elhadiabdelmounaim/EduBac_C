import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from education.models import Course, Lesson
from quizzes.models import Quiz, Question, QuizGenerationQuestion
from .quiz_novelty import (
    history_instruction, previous_questions, reserve_questions,
    signature, validate_local, validate_semantic,
)
from .quiz_validation import validate_question
from .services import AIService
from .test_quiz_protocol import ANALYSIS, generated, question, repaired, reviews


@override_settings(ALLOWED_HOSTS=["testserver"], QUIZ_SEMANTIC_CHECK_ENABLED=True)
class DuplicateChecksDisabledTests(TestCase):
    """Exercise the real default, even if the older semantic setting is enabled."""

    def setUp(self):
        self.teacher = User.objects.create_user(
            username="repetition-allowed", email="repetition@example.test", role="teacher",
        )
        self.lesson = Lesson.objects.create(
            title="Calculs", course=Course.objects.create(name="Mathématiques", niveau="tronc_commun"),
        )
        self.original = question()
        self.archived = QuizGenerationQuestion.objects.create(
            lesson=self.lesson, signature=signature(self.original), data=self.original,
        )
        session = self.client.session
        session["user_id"] = self.teacher.pk
        session.save()

    def test_question_comparison_is_disabled_in_the_application_default(self):
        self.assertFalse(settings.QUIZ_DUPLICATE_CHECK_ENABLED)

    def test_no_history_queries_comparison_calls_or_unique_reservations(self):
        service = Mock()
        with self.assertNumQueries(0):
            self.assertEqual(previous_questions(self.lesson), [])
            self.assertEqual(history_instruction([self.original]), "")
            validate_local([self.original, self.original], [self.original])
            self.assertIsNone(validate_semantic(service, [self.original], [self.original]))
            self.assertEqual(validate_semantic(
                service, [self.original, self.original], [self.original], collect=True,
            ), set())
            reserve_questions(service, self.lesson, [self.original, self.original], [self.original])
        service.assert_not_called()
        service._chat.assert_not_called()
        self.assertEqual(QuizGenerationQuestion.objects.count(), 1)

    @patch.object(AIService, "_get_provider", return_value=SimpleNamespace(name="test", model="test"))
    def test_teacher_saves_repeated_questions_from_sources_and_prior_generations(self, provider):
        stages = []

        def response(messages, **kwargs):
            system = messages[0]["content"]
            if "ÉTAPE 1" in system:
                stages.append("analysis")
                return json.dumps({**ANALYSIS, "reference_segments": [1]})
            if "ÉTAPE 4" in system:
                stages.append("math")
                return reviews(1, 2)
            if "diversité" in system:
                self.fail("Duplicate detection must not call the model.")
            stages.append("generation")
            self.assertNotIn("DIVERSITÉ OBLIGATOIRE", messages[1]["content"])
            return generated(self.original, self.original)

        with patch.object(AIService, "_chat", side_effect=response):
            for _ in range(2):
                result = self.client.post(reverse("quizzes:teacher_ai"), {
                    "lesson": self.lesson.pk, "niveau": "tronc_commun", "action": "generate",
                    "description": "Évaluer des calculs simples.", "question_count": 2,
                    "resource_selection_present": "1", "generation_mode": "resources",
                    "resource_uploads": SimpleUploadedFile(
                        "exemple.txt", ("Exemple : " + self.original["text"]).encode(),
                    ),
                })
                self.assertIsNone(result.context["error"])
                self.assertFalse(result.context["generation_report"]["history_checked"])
                self.assertContains(result, "Le contrôle de répétition des questions est désactivé.")
                self.assertNotContains(result, "historique consulté")
        self.assertEqual(stages, ["analysis", "generation", "math"] * 2)
        self.assertEqual(Quiz.objects.count(), 2)
        self.assertEqual(Question.objects.filter(text=self.original["text"]).count(), 4)
        self.assertEqual(QuizGenerationQuestion.objects.count(), 1)
        self.assertEqual(QuizGenerationQuestion.objects.get().pk, self.archived.pk)

    @patch.object(AIService, "_get_provider", return_value=SimpleNamespace(name="test", model="test"))
    def test_incorrect_math_still_blocks_saving_after_targeted_repairs(self, provider):
        bad = question(answer="6")
        stages = []

        def response(messages, **kwargs):
            if "ÉTAPE 1" in messages[0]["content"]:
                return json.dumps(ANALYSIS)
            if "ÉTAPE 4" in messages[0]["content"]:
                stages.append("math")
                return reviews()
            if messages[-1]["content"].startswith(("CORRIGE", "REMPLACE")):
                stages.append("repair")
                return repaired(bad)
            return generated(bad)

        with patch.object(AIService, "_chat", side_effect=response):
            result = self.client.post(reverse("quizzes:teacher_ai"), {
                "lesson": self.lesson.pk, "niveau": "tronc_commun", "action": "generate",
                "description": "Calculer une somme.", "question_count": 1,
                "generation_mode": "topic", "resource_selection_present": "1",
            })
        self.assertIsNotNone(result.context["error"])
        self.assertEqual(stages, ["math", "repair", "math", "repair", "math"])
        self.assertFalse(Quiz.objects.exists())
        self.assertEqual(QuizGenerationQuestion.objects.count(), 1)

    def test_answer_choices_must_still_be_distinct(self):
        invalid = question()
        invalid["choices"][1]["text"] = invalid["choices"][0]["text"]
        with self.assertRaises(ValueError):
            validate_question(invalid, 1)
