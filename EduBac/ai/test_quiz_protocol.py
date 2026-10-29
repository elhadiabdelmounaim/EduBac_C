import json
import uuid
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from django.db import OperationalError
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from education.models import Course, Lesson
from quizzes.models import Quiz, Question, QuizGenerationQuestion
from .providers import AIProviderError
from .services import AIService
from .quiz_protocol import exact_answer_error
from .quiz_novelty import validate_semantic


ANALYSIS = {
    "compatible": True, "reason": "Calculs adaptés au sujet et au niveau.",
    "skills": ["Calculer et justifier"], "reference_questions": [],
}


def question(text="Calculer $2+3$.", answer="5"):
    others = [str(n) for n in (4, 6, 7, 8, 9) if str(n) != answer][:3]
    return {
        "text": text, "choices": [{"text": answer, "is_correct": True}]
        + [{"text": n, "is_correct": False} for n in others],
        "explanation": "La somme de deux et trois vaut cinq.", "hint": "Effectuer le calcul.",
    }


SECOND = question("Une boîte contient trois lots de quatre crayons. Combien de crayons contient-elle ?", "12")
SECOND["explanation"] = "Trois fois quatre vaut douze."


def generated(*questions):
    return json.dumps({"title": "Quiz contrôlé", "questions": questions}, ensure_ascii=False)


def reviews(*indexes, **overrides):
    entries = []
    for index in indexes or (1,):
        item = {
            "index": index, "valid_question": True, "valid_explanation": True,
            "on_topic": True, "suitable_level": True, "difficulty_ok": True,
            "correct_choices": [1], "reason": "Question valide.",
            "solution": "Résolution indépendante vérifiée.", "competency": "Effectuer un calcul justifié",
        }
        item.update(overrides)
        entries.append(item)
    return json.dumps({"reviews": entries}, ensure_ascii=False)


def repaired(candidate, index=1):
    return json.dumps({"questions": [{"index": index, **candidate}]}, ensure_ascii=False)


@override_settings(ALLOWED_HOSTS=["testserver"], QUIZ_SEMANTIC_CHECK_ENABLED=False)
class QuizProtocolTests(TestCase):
    def setUp(self):
        self.lesson = Lesson.objects.create(
            title="Calculs et équations", content="Ce contenu ne doit pas être lu implicitement.",
            course=Course.objects.create(name="Mathématiques", niveau="tronc_commun"),
        )
        provider = patch.object(AIService, "_get_provider", return_value=SimpleNamespace(name="test", model="test"))
        provider.start()
        self.addCleanup(provider.stop)
        sleep = patch("ai.services.time.sleep")
        sleep.start()
        self.addCleanup(sleep.stop)
        self.service = AIService()

    def run_protocol(self, count=1, **kwargs):
        return self.service.generate_quiz_from_lesson(
            self.lesson, count, "moyen", resource_context=kwargs.pop("resource_context", ""),
            description="Calculs et équations, situations variées et raisonnements justifiés.",
            allow_related_knowledge=True, enforce_protocol=True, **kwargs,
        )

    @patch.object(AIService, "_chat")
    def test_analysis_history_generation_blind_review_and_reservation_are_ordered(self, chat):
        events = []
        from .quiz_protocol import load_history
        def history(lesson):
            events.append("history")
            return load_history(lesson)
        def response(messages, **kwargs):
            system = messages[0]["content"]
            if "ÉTAPE 1" in system:
                events.append("analysis")
                return json.dumps(ANALYSIS)
            if "ÉTAPE 4" in system:
                events.append("review")
                payload = json.loads(messages[1]["content"])
                self.assertNotIn("is_correct", json.dumps(payload["questions"]))
                self.assertNotIn("correct_answer", json.dumps(payload["questions"]))
                return reviews()
            events.append("generation")
            return generated(question())
        chat.side_effect = response
        with patch("ai.quiz_protocol.load_history", side_effect=history), patch.object(
            Lesson, "get_ai_help", side_effect=AssertionError("No implicit sources")
        ):
            data = self.run_protocol()
        self.assertEqual(events, ["analysis", "history", "generation", "review"])
        row = QuizGenerationQuestion.objects.get()
        item = data["questions"][0]
        self.assertEqual(row.data["id"], item["id"])
        uuid.UUID(item["id"])
        self.assertEqual(item["correct_index"], 0)
        self.assertEqual(item["lesson_reference"], str(self.lesson.pk))
        self.assertEqual(item["difficulty"], "moyen")
        self.assertTrue(item["competency"])
        self.assertEqual(data["_generation_report"]["history_questions"], 0)
        self.assertTrue(data["_generation_report"]["history_checked"])
        self.assertIsNone(self.service._quiz_deadline)
        self.assertFalse(self.service._quiz_protocol_active)

    @patch.object(AIService, "_chat")
    def test_incompatible_source_stops_before_history_and_generation(self, chat):
        chat.return_value = json.dumps({**ANALYSIS, "compatible": False, "reason": "Sujet sans rapport."})
        with patch("ai.quiz_protocol.load_history") as history, self.assertRaises(AIProviderError) as error:
            self.run_protocol(resource_context="Une source sans rapport.")
        self.assertEqual(error.exception.code, "invalid_source")
        self.assertEqual(chat.call_count, 1)
        history.assert_not_called()
        self.assertFalse(QuizGenerationQuestion.objects.exists())

    @patch.object(AIService, "_chat")
    def test_fabricated_source_reference_is_never_accepted(self, chat):
        chat.return_value = json.dumps({**ANALYSIS, "reference_questions": ["Exemple inventé"]})
        with self.assertRaises(AIProviderError):
            self.run_protocol(resource_context="Définition seulement.")
        self.assertEqual(chat.call_count, 1)

    @patch.object(AIService, "_chat", return_value=json.dumps(ANALYSIS))
    def test_unavailable_history_is_reported_without_false_verification(self, chat):
        with patch("ai.quiz_protocol.previous_questions", side_effect=OperationalError("Unavailable")):
            with self.assertRaises(AIProviderError) as error:
                self.run_protocol()
        self.assertEqual(error.exception.code, "history_unavailable")
        self.assertIn("Historique inaccessible", str(error.exception))
        self.assertEqual(chat.call_count, 1)
        self.assertFalse(QuizGenerationQuestion.objects.exists())

    @patch.object(AIService, "_chat")
    def test_analysis_and_review_responses_fail_closed(self, chat):
        for responses in (["{}"], [json.dumps(ANALYSIS), generated(question()), "{}"]):
            with self.subTest(responses=len(responses)):
                chat.side_effect = responses
                with self.assertRaises(AIProviderError) as error:
                    self.run_protocol()
                self.assertEqual(error.exception.code, "protocol_validation_failed")
                self.assertFalse(QuizGenerationQuestion.objects.exists())

    @patch.object(AIService, "_chat")
    def test_semantic_check_is_mandatory_even_when_legacy_flag_is_disabled(self, chat):
        chat.side_effect = [
            json.dumps(ANALYSIS), generated(question(), SECOND), reviews(1, 2),
            '{"similar_questions":[]}',
        ]
        data = self.run_protocol(count=2)
        self.assertEqual(chat.call_count, 4)
        self.assertIn("diversité", chat.call_args_list[-1].args[0][0]["content"])
        self.assertEqual(len(data["questions"]), 2)
        self.assertEqual(len({q["id"] for q in data["questions"]}), 2)

    @patch.object(AIService, "_chat")
    def test_only_semantically_refused_question_is_replaced(self, chat):
        alternative = question("Résoudre $2x+3=11$.", "4")
        alternative["explanation"] = "Soustraire trois puis diviser par deux donne quatre."
        chat.side_effect = [
            json.dumps(ANALYSIS), generated(question(), SECOND), reviews(1, 2),
            '{"similar_questions":[2]}', repaired(alternative, 2), reviews(2),
            '{"similar_questions":[]}',
        ]
        data = self.run_protocol(count=2)
        for key, value in question().items():
            self.assertEqual(data["questions"][0][key], value)
        self.assertEqual(data["questions"][1]["text"], alternative["text"])
        self.assertIn("CORRIGE uniquement", chat.call_args_list[4].args[0][-1]["content"])

    @patch.object(AIService, "_chat")
    def test_exact_arithmetic_overrules_an_incorrect_ai_approval(self, chat):
        wrong = question(answer="6")
        wrong["choices"][2]["text"] = "5"
        chat.side_effect = [
            json.dumps(ANALYSIS), generated(wrong), reviews(), repaired(question()), reviews(),
        ]
        data = self.run_protocol()
        self.assertEqual(data["questions"][0]["correct_answer"], "5")
        self.assertIn("calcul rationnel", chat.call_args_list[3].args[0][-1]["content"].lower())
        self.assertEqual(data["_generation_report"]["checks"][0]["verification"], "rational_exact_and_ai")

    @patch.object(AIService, "_chat")
    def test_false_premise_is_repaired_without_touching_valid_question(self, chat):
        bad = question("Quelle erreur contient la résolution $4x-7=9$, $4x=16$, $x=4$ ?", "Ajouter sept")
        rejected = json.loads(reviews(1, 2))
        rejected["reviews"][1].update(valid_question=False, correct_choices=[],
                                      reason="La résolution est correcte ; la prémisse est fausse.")
        chat.side_effect = [
            json.dumps(ANALYSIS), generated(question(), bad), json.dumps(rejected),
            repaired(SECOND, 2), reviews(2), '{"similar_questions":[]}',
        ]
        data = self.run_protocol(count=2)
        for key, value in question().items():
            self.assertEqual(data["questions"][0][key], value)
        self.assertEqual(data["questions"][1]["text"], SECOND["text"])

    @patch.object(AIService, "_chat")
    def test_correction_then_replacement_and_no_invalid_reservation(self, chat):
        rejected = reviews(valid_explanation=False, reason="Explication mathématiquement fausse.")
        chat.side_effect = [
            json.dumps(ANALYSIS), generated(question()), rejected, repaired(question()),
            rejected, repaired(question()), rejected,
        ]
        with self.assertRaises(AIProviderError) as error:
            self.run_protocol()
        self.assertEqual(error.exception.code, "invalid_question")
        self.assertIn("REMPLACE uniquement", chat.call_args_list[5].args[0][-1]["content"])
        self.assertEqual(chat.call_count, 7)
        self.assertFalse(QuizGenerationQuestion.objects.exists())

    @patch.object(AIService, "_chat")
    def test_exercises_from_source_are_compared_before_retaining_question(self, chat):
        source_question = SECOND["text"]
        chat.side_effect = [
            json.dumps({**ANALYSIS, "reference_questions": [source_question]}),
            generated(question()), reviews(), '{"similar_questions":[]}',
        ]
        data = self.run_protocol(resource_context=source_question)
        compared = json.loads(chat.call_args_list[-1].args[0][1]["content"])
        self.assertIn(source_question, [q["text"] for q in compared["previous_questions"]])
        self.assertEqual(data["_generation_report"]["source_reference_questions"], 1)

    @patch.object(AIService, "_chat")
    def test_labelled_source_example_is_compared_even_if_analysis_omits_it(self, chat):
        chat.side_effect = [json.dumps(ANALYSIS), generated(question()), reviews(),
                            '{"similar_questions":[]}']
        data = self.run_protocol(resource_context="Définition des calculs.\nExemple : " + SECOND["text"])
        payload = json.loads(chat.call_args_list[-1].args[0][1]["content"])
        self.assertIn(SECOND["text"], [q["text"] for q in payload["previous_questions"]])
        self.assertEqual(data["_generation_report"]["source_reference_questions"], 1)

    @patch.object(AIService, "_chat")
    def test_all_prior_quiz_and_reserved_questions_are_consulted(self, chat):
        old = Quiz.objects.create(title="Ancien quiz", lesson=self.lesson)
        Question.objects.create(quiz=old, text="Quelle est la définition d’une fraction ?", explanation="Définition.")
        QuizGenerationQuestion.objects.create(
            lesson=self.lesson, signature="prior-reserved", data={"text": SECOND["text"]},
        )
        chat.side_effect = [json.dumps(ANALYSIS), generated(question()), reviews(), '{"similar_questions":[]}']
        data = self.run_protocol()
        payload = json.loads(chat.call_args_list[-1].args[0][1]["content"])
        self.assertEqual(len(payload["previous_questions"]), 2)
        self.assertEqual(data["_generation_report"]["history_questions"], 2)

    @patch.object(AIService, "_chat")
    def test_invalid_semantic_response_does_not_trigger_whole_quiz_regeneration(self, chat):
        chat.side_effect = [json.dumps(ANALYSIS), generated(question(), SECOND), reviews(1, 2), "{}"]
        with self.assertRaises(AIProviderError) as error:
            self.run_protocol(count=2)
        self.assertEqual(error.exception.code, "novelty_validation_failed")
        self.assertEqual(chat.call_count, 4)
        self.assertFalse(QuizGenerationQuestion.objects.exists())

    @patch.object(AIService, "_chat")
    def test_review_rejects_missing_duplicate_and_boolean_indexes(self, chat):
        for invalid in ({"reviews": []}, {"reviews": [json.loads(reviews())["reviews"][0]] * 2},
                        json.loads(reviews(correct_choices=[True]))):
            chat.side_effect = [json.dumps(ANALYSIS), generated(question()), json.dumps(invalid)]
            with self.subTest(invalid=invalid), self.assertRaises(AIProviderError):
                self.run_protocol()
        self.assertFalse(QuizGenerationQuestion.objects.exists())

    def test_exact_checker_is_narrow_and_never_claims_general_proof(self):
        self.assertEqual(exact_answer_error(question()), "")
        self.assertIsNone(exact_answer_error(SECOND))
        malicious = question('Calculer $__import__("os").system("false")$.')
        self.assertIsNone(exact_answer_error(malicious))
        equivalent = question("Résoudre $2x=12$.", "6")
        equivalent["choices"][1]["text"] = "6.0"
        self.assertIn("contredit", exact_answer_error(equivalent))

    @patch.object(AIService, "_chat")
    def test_teacher_route_saves_only_after_full_protocol_and_displays_honest_report(self, chat):
        teacher = User.objects.create_user(
            username="protocol-teacher", email="protocol-teacher@example.test", role="teacher",
        )
        session = self.client.session
        session["user_id"] = teacher.pk
        session.save()
        chat.side_effect = [json.dumps(ANALYSIS), generated(question()), reviews()]
        response = self.client.post(reverse("quizzes:teacher_ai"), {
            "lesson": self.lesson.pk, "niveau": "tronc_commun", "question_count": 1,
            "description": "Évaluer le calcul numérique sans fichier.", "action": "generate",
            "generation_mode": "topic", "resource_selection_present": "1",
        })
        self.assertIsNone(response.context["error"])
        self.assertEqual(Quiz.objects.count(), 1)
        self.assertEqual(QuizGenerationQuestion.objects.count(), 1)
        self.assertContains(response, "La revue croisée par IA ne constitue pas une preuve mathématique générale")
        self.assertEqual(response.context["generation_report"]["reviewed_questions"], 1)

    @patch.object(AIService, "_chat")
    def test_semantic_collect_covers_every_history_and_new_question_batch(self, chat):
        history = [{"text": f"Ancienne question {i}"} for i in range(51)]
        fresh = [{"text": f"Nouvelle question {i}"} for i in range(6)]
        seen = set()
        def verdict(messages, **kwargs):
            payload = json.loads(messages[1]["content"])
            seen.update(q["text"] for q in payload["previous_questions"])
            indexes = [q["index"] for q in payload["new_questions"] if q["index"] in (2, 6)]
            return json.dumps({"similar_questions": indexes})
        chat.side_effect = verdict
        self.assertEqual(validate_semantic(self.service, fresh, history, collect=True), {2, 6})
        self.assertTrue({q["text"] for q in history}.issubset(seen))

    @patch.object(AIService, "_chat")
    def test_rate_limit_retries_same_review_not_generation(self, chat):
        chat.side_effect = [
            json.dumps(ANALYSIS), generated(question()),
            AIProviderError("Rate limit", code="rate_limit"), reviews(),
        ]
        with patch.object(self.service, "_maybe_wait_for_rate_limit", return_value=True):
            self.run_protocol()
        self.assertEqual(chat.call_args_list[2].args[0], chat.call_args_list[3].args[0])
        self.assertIn("ÉTAPE 4", chat.call_args_list[3].args[0][0]["content"])
        self.assertEqual(chat.call_count, 4)

    @patch.object(AIService, "_chat")
    def test_unrecoverable_review_failure_never_restarts_quiz(self, chat):
        chat.side_effect = [
            json.dumps(ANALYSIS), generated(question()),
            AIProviderError("Unavailable", code="timeout"),
        ]
        with self.assertRaises(AIProviderError) as error:
            self.run_protocol()
        self.assertEqual(error.exception.code, "timeout")
        self.assertEqual(chat.call_count, 3)
        self.assertFalse(QuizGenerationQuestion.objects.exists())

    @patch.object(AIService, "_chat")
    def test_concurrent_history_is_rechecked_even_with_legacy_flag_disabled(self, chat):
        chat.side_effect = [json.dumps(ANALYSIS), generated(question()), reviews()]
        # The initial snapshot is empty; the reservation sees a concurrent duplicate.
        with patch("ai.quiz_novelty.previous_questions", return_value=[question()]):
            with self.assertRaises(AIProviderError) as error:
                self.run_protocol()
        self.assertEqual(error.exception.code, "invalid_question")
        self.assertIn("historique a changé", str(error.exception))
        self.assertEqual(chat.call_count, 3)
        self.assertFalse(QuizGenerationQuestion.objects.exists())
