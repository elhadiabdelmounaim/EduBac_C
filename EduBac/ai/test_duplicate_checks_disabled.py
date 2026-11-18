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
from .services import repair_latex_escapes
from .quiz_protocol import review_questions
from .providers import AIProviderError
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
        # La génération interne par IA est désactivée côté enseignant (import JSON seulement) :
        # la route refuse, n'appelle aucun modèle et ne crée aucun quiz.
        with patch.object(AIService, "_chat") as chat:
            response = self.client.post(reverse("quizzes:teacher_ai"), {
                "lesson": self.lesson.pk, "niveau": "tronc_commun", "action": "generate",
                "description": "Calculer une somme.", "question_count": 1,
                "generation_mode": "topic", "resource_selection_present": "1",
            })
        self.assertEqual(response.status_code, 200)
        self.assertIn("La génération interne est désactivée", response.context["error"])
        self.assertFalse(Quiz.objects.exists())
        chat.assert_not_called()

    @patch.object(AIService, "_get_provider", return_value=SimpleNamespace(name="test", model="test"))
    def test_incorrect_math_still_blocks_saving_after_targeted_repairs(self, provider):
        # La génération interne par IA est désactivée côté enseignant (import JSON seulement) :
        # la route refuse, n'appelle aucun modèle et ne crée aucun quiz.
        with patch.object(AIService, "_chat") as chat:
            response = self.client.post(reverse("quizzes:teacher_ai"), {
                "lesson": self.lesson.pk, "niveau": "tronc_commun", "action": "generate",
                "description": "Calculer une somme.", "question_count": 1,
                "generation_mode": "topic", "resource_selection_present": "1",
            })
        self.assertEqual(response.status_code, 200)
        self.assertIn("La génération interne est désactivée", response.context["error"])
        self.assertFalse(Quiz.objects.exists())
        chat.assert_not_called()

    def test_answer_choices_must_still_be_distinct(self):
        invalid = question()
        invalid["choices"][1]["text"] = invalid["choices"][0]["text"]
        with self.assertRaises(ValueError):
            validate_question(invalid, 1)

    def test_ai_latex_errors_from_real_generation_are_repaired_only_inside_math(self):
        source = r"$u_{n+1}=q,u_n;\ v_n=v_0-ncdot3;\ n ge 0$ — ncdot3"
        result = repair_latex_escapes(json.dumps({"text": source}))["text"]
        self.assertEqual(
            result, r"$u_{n+1}=q\,u_n;\ v_n=v_0-n\cdot3;\ n\ge 0$ — ncdot3",
        )

    @patch.object(AIService, "_chat", return_value=reviews())
    def test_math_review_checks_every_polynomial_root_and_latex_operation(self, chat):
        service = AIService()
        with patch.object(
            service, "_get_provider", return_value=SimpleNamespace(name="test", model="test"),
        ):
            review_questions(
                service,
                [question("Pour $g'(x)=2x^3-6x^2+5x-1$, où la tangente est-elle horizontale ?")],
                [0], {"niveau": "1ère Bac"}, "", "moyen",
            )
        review_prompt = chat.call_args.args[0][0]["content"]
        self.assertIn("toutes les solutions réelles", review_prompt.lower())
        self.assertIn("vérifie que chaque formule", review_prompt.lower())

    def test_math_rejection_without_a_competency_does_not_abort_the_entire_quiz(self):
        response = json.loads(reviews(1, 2))
        response["reviews"][0].update(
            valid_question=False, valid_explanation=False, correct_choices=[],
            reason="La question comporte plusieurs racines réelles.",
            solution="Le polynôme dérivé possède trois racines réelles.",
            competency=None,
        )
        service = AIService()
        with patch.object(
            service, "_get_provider", return_value=SimpleNamespace(name="test", model="test"),
        ), patch.object(AIService, "_chat", return_value=json.dumps(response)):
            result = review_questions(
                service, [question(), question("Calculer $3+4$.", "7")], [0, 1],
                {"niveau": "1ère Bac"}, "", "moyen",
            )
        self.assertIn("plusieurs racines", result[0]["error"])
        self.assertEqual(
            result[0]["competency"], "Compétence à confirmer après correction.",
        )
        self.assertFalse(result[1]["error"])
        self.assertEqual(result[1]["competency"], "Effectuer un calcul justifié")

    @patch.object(AIService, "_get_provider", return_value=SimpleNamespace(name="test", model="test"))
    def test_teacher_repairs_a_rejected_question_even_when_review_omits_competency(self, provider):
        bad = question(answer="6")
        rejection = json.loads(reviews(
            valid_question=False, valid_explanation=False, correct_choices=[],
            reason="La réponse numérique est incorrecte.",
            solution="Le calcul donne cinq, non six.",
            competency=None,
        ))
        calls = []

        def response(messages, **kwargs):
            system, prompt = messages[0]["content"], messages[-1]["content"]
            if "ÉTAPE 1" in system:
                calls.append("analysis")
                return json.dumps(ANALYSIS)
            if "ÉTAPE 4" in system:
                calls.append("math")
                return json.dumps(rejection) if calls.count("math") == 1 else reviews()
            if prompt.startswith(("CORRIGE uniquement", "REMPLACE uniquement")):
                calls.append("repair")
                return repaired(question())
            calls.append("generation")
            return generated(bad)

        service = AIService()
        with patch.object(AIService, "_chat", side_effect=response):
            data = service.generate_quiz_from_lesson(
                self.lesson, 1, "moyen", resource_context="", allow_related_knowledge=True,
                enforce_protocol=True,
            )
        self.assertEqual(calls, ["analysis", "generation", "math", "repair", "math"])
        self.assertEqual(data["questions"][0]["correct_answer"], "5")

    def test_missing_competency_for_a_accepted_question_still_fails_closed(self):
        response = json.loads(reviews())
        response["reviews"][0]["competency"] = None
        service = AIService()
        with patch.object(
            service, "_get_provider", return_value=SimpleNamespace(name="test", model="test"),
        ), patch.object(AIService, "_chat", return_value=json.dumps(response)):
            with self.assertRaisesRegex(AIProviderError, "compétence"):
                review_questions(
                    service, [question()], [0], {"niveau": "Tronc Commun"}, "", "moyen",
                )
