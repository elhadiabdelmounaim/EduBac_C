import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from education.models import Course, Lesson
from quizzes.models import Quiz, QuizGenerationQuestion
from .providers import AIProviderError
from .quiz_validation import validate_question
from .services import AIService


def question(text="Calculer $2+3$.", answer="5"):
    return {
        "text": text,
        "choices": [
            {"text": answer, "is_correct": True},
            {"text": "4", "is_correct": False},
            {"text": "6", "is_correct": False},
            {"text": "7", "is_correct": False},
        ],
        "correct_answer": answer,
        "explanation": "On additionne les deux nombres.",
        "hint": "Utilise l’addition.",
    }


def response(*questions):
    return json.dumps({"title": "Quiz à conserver", "questions": questions}, ensure_ascii=False)


@override_settings(ALLOWED_HOSTS=["testserver"], QUIZ_SEMANTIC_CHECK_ENABLED=True)
class QuizQuestionValidationTests(TestCase):
    def setUp(self):
        self.lesson = Lesson.objects.create(
            title="Calcul numérique", content="Addition, fractions, puissances et géométrie.",
            course=Course.objects.create(name="Mathématiques", niveau="tronc_commun"),
        )
        self.service = AIService()
        provider = patch.object(AIService, "_get_provider", return_value=SimpleNamespace(
            name="test", model="test-model",
        ))
        provider.start()
        self.addCleanup(provider.stop)
        sleep = patch("ai.services.time.sleep")
        sleep.start()
        self.addCleanup(sleep.stop)
        self.good = question()
        self.broken = question("Factoriser $x^2-9$.", "$(x-3)(x+3)$")
        self.fixed = deepcopy(self.broken)
        self.broken["choices"] = [self.broken["choices"][0]]

    def test_choices_must_be_a_nonempty_list_with_two_or_more_distinct_texts(self):
        for choices in (None, [], ["5"], "5, 4", {"A": "5", "B": "4"},
                        ["5", ""], ["5", " 5 "], ["5", 4], ["5", {"is_correct": False}]):
            with self.subTest(choices=choices):
                candidate = question()
                candidate["choices"] = choices
                with self.assertRaises(ValueError):
                    validate_question(candidate, 5)
        candidate = question()
        del candidate["choices"]
        with self.assertRaises(ValueError):
            validate_question(candidate, 5)

    def test_missing_wrong_ambiguous_or_conflicting_answer_is_rejected(self):
        for mode in ("missing", "wrong", "multiple", "contradiction", "nonboolean", "numeric_index"):
            candidate = question()
            if mode == "missing":
                del candidate["correct_answer"]
                candidate["choices"][0]["is_correct"] = False
            elif mode == "wrong":
                candidate["correct_answer"] = "Réponse absente"
            elif mode == "multiple":
                candidate["choices"][1]["is_correct"] = True
            elif mode == "contradiction":
                candidate["correct_answer"] = "4"
            elif mode == "nonboolean":
                candidate["choices"][0]["is_correct"] = "true"
            else:
                candidate["correct_answer"] = "0"  # not an answer text; must not become index 0
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                validate_question(candidate, 1)

    def test_string_choices_and_question_alias_are_normalized(self):
        candidate = {"question": "Choisir la réponse.", "choices": ["Réponse A", "Réponse B"],
                     "correct_answer": "Réponse B"}
        validated = validate_question(candidate, 1)
        self.assertEqual(validated["text"], candidate["question"])
        self.assertEqual(validated["correct_answer"], "Réponse B")
        self.assertEqual([c["is_correct"] for c in validated["choices"]], [False, True])
        self.assertEqual(candidate["choices"], ["Réponse A", "Réponse B"])

    def test_letter_reference_and_single_correct_flag_resolve_to_actual_choice(self):
        candidate = {"text": "Choisir.", "choices": ["Oui", "Non"], "correct_answer": "B"}
        self.assertEqual(validate_question(candidate, 1)["correct_answer"], "Non")
        candidate = question()
        del candidate["correct_answer"]
        self.assertEqual(validate_question(candidate, 1)["correct_answer"], "5")

    def test_zero_is_an_answer_text_not_a_false_missing_value(self):
        candidate = {"text": "Choisir.", "choices": ["0", "1"], "correct_answer": 0}
        self.assertEqual(validate_question(candidate, 1)["correct_answer"], "0")

    def test_latex_and_mathematical_case_are_preserved(self):
        candidate = {"text": r"Choisir $f(x)$.", "choices": ["$f(x)$", "$F(x)$"],
                     "correct_answer": "$F(x)$", "explanation": r"$\frac{1}{2}$"}
        validated = validate_question(candidate, 1)
        self.assertEqual(validated["correct_answer"], "$F(x)$")
        self.assertEqual(validated["explanation"], r"$\frac{1}{2}$")

    @patch.object(AIService, "_chat")
    def test_one_invalid_question_is_repaired_without_regenerating_valid_question(self, chat):
        chat.side_effect = [response(self.good, self.broken), response(self.fixed),
                            '{"similar_questions":[]}']
        result = self.service.generate_quiz_from_lesson(
            self.lesson, 2, "difficile", description="Priorité aux fractions.",
        )
        self.assertEqual(result["questions"], [self.good, self.fixed])
        self.assertEqual(result["title"], "Quiz à conserver")
        self.assertEqual(chat.call_count, 3)
        prompt = chat.call_args_list[1].args[0]
        self.assertIn("CORRIGE uniquement", prompt[-1]["content"])
        self.assertIn("Priorité aux fractions.", prompt[1]["content"])
        self.assertIn("difficile", prompt[1]["content"])
        self.assertIn("exactement 4 choix de réponse distincts", prompt[1]["content"])
        self.assertEqual(QuizGenerationQuestion.objects.count(), 2)

    @patch.object(AIService, "_chat")
    def test_failed_repair_is_followed_by_a_replacement_only_for_invalid_slot(self, chat):
        replacement = question("Quelle est l’aire d’un disque de rayon $3$ ?", "$9\\pi$")
        chat.side_effect = [response(self.good, self.broken), response(self.broken),
                            response(replacement), '{"similar_questions":[]}']
        result = self.service.generate_quiz_from_lesson(self.lesson, 2)
        self.assertEqual(result["questions"], [self.good, replacement])
        self.assertIn("REMPLACE uniquement", chat.call_args_list[2].args[0][-1]["content"])
        self.assertEqual(chat.call_count, 4)

    @patch.object(AIService, "_chat")
    def test_malformed_repair_json_does_not_discard_valid_questions(self, chat):
        chat.side_effect = [response(self.good, self.broken), '{"questions": [',
                            response(self.fixed), '{"similar_questions":[]}']
        result = self.service.generate_quiz_from_lesson(self.lesson, 2)
        self.assertEqual(result["questions"], [self.good, self.fixed])

    @patch.object(AIService, "_chat")
    def test_rate_limit_during_repair_stops_without_another_question_attempt(self, chat):
        chat.side_effect = [
            response(self.good, self.broken),
            AIProviderError("Rate limit", code="rate_limit", retry_after=90),
        ]
        with self.assertRaises(AIProviderError) as error:
            self.service.generate_quiz_from_lesson(self.lesson, 2)
        self.assertEqual(error.exception.code, "rate_limit")
        self.assertEqual(chat.call_count, 2)
        self.assertFalse(QuizGenerationQuestion.objects.exists())

    @patch.object(AIService, "_chat")
    def test_provider_failure_during_repair_still_attempts_replacement(self, chat):
        chat.side_effect = [response(self.good, self.broken),
                            AIProviderError("Temporary issue", code="connection"),
                            response(self.fixed), '{"similar_questions":[]}']
        result = self.service.generate_quiz_from_lesson(self.lesson, 2)
        self.assertEqual(result["questions"][0], self.good)
        self.assertEqual(result["questions"][1], self.fixed)

    @patch.object(AIService, "_chat")
    def test_question_five_repair_keeps_all_other_questions_and_order(self, chat):
        existing = [
            question("Calculer $2+3$."),
            question("Exprimer le périmètre d’un rectangle de côtés $a$ et $b$."),
            question("Identifier une fraction irréductible parmi les propositions."),
            question("Quel signe possède le produit de deux nombres négatifs ?"),
        ]
        chat.side_effect = [response(*existing, self.broken), response(self.fixed),
                            '{"similar_questions":[]}']
        result = self.service.generate_quiz_from_lesson(self.lesson, 5)
        self.assertEqual(result["questions"], existing + [self.fixed])
        self.assertIn("Question 5 doit avoir au moins 2 choix", chat.call_args_list[1].args[0][-1]["content"])

    @patch.object(AIService, "_chat")
    def test_all_questions_are_validated_before_return(self, chat):
        candidate = deepcopy(self.broken)
        candidate["choices"] = "not a list"
        chat.side_effect = [response(candidate), response(self.fixed)]
        result = self.service.generate_quiz_from_lesson(self.lesson, 1)
        for q in result["questions"]:
            self.assertIsInstance(q["choices"], list)
            self.assertGreaterEqual(len(q["choices"]), 2)
            self.assertEqual(sum(c["is_correct"] for c in q["choices"]), 1)
            self.assertIn(q["correct_answer"], [c["text"] for c in q["choices"]])
        self.assertEqual(chat.call_count, 2)

    @patch.object(AIService, "_chat")
    def test_multiple_invalid_slots_are_repaired_in_place(self, chat):
        other = question("Quel est le périmètre d’un carré de côté $3$ ?", "12")
        invalid_other = deepcopy(other)
        del invalid_other["choices"]
        chat.side_effect = [response(self.broken, self.good, invalid_other),
                            response(self.fixed), response(other), '{"similar_questions":[]}']
        result = self.service.generate_quiz_from_lesson(self.lesson, 3)
        self.assertEqual(result["questions"], [self.fixed, self.good, other])
        self.assertEqual(chat.call_count, 4)

    @patch.object(AIService, "_chat")
    def test_repair_cannot_duplicate_a_valid_question(self, chat):
        chat.side_effect = [response(self.good, self.broken), response(self.good),
                            response(self.fixed), '{"similar_questions":[]}']
        result = self.service.generate_quiz_from_lesson(self.lesson, 2)
        self.assertEqual(result["questions"], [self.good, self.fixed])
        self.assertIn("REMPLACE uniquement", chat.call_args_list[2].args[0][-1]["content"])

    @patch.object(AIService, "_chat")
    def test_failure_never_returns_or_reserves_an_invalid_quiz_or_restarts_whole_quiz(self, chat):
        chat.side_effect = [response(self.good, self.broken), response(self.broken), response(self.broken)]
        with self.assertRaises(AIProviderError) as error:
            self.service.generate_quiz_from_lesson(self.lesson, 2)
        self.assertEqual(error.exception.code, "invalid_question")
        self.assertEqual(chat.call_count, 3)
        self.assertFalse(QuizGenerationQuestion.objects.exists())

    @patch.object(AIService, "_chat")
    def test_teacher_route_saves_only_valid_repaired_quiz(self, chat):
        user = User.objects.create_user(username="qcm-teacher", email="qcm@example.test", role="teacher")
        session = self.client.session
        session["user_id"] = user.pk
        session.save()
        chat.side_effect = [response(self.good, self.broken), response(self.fixed),
                            '{"similar_questions":[]}']
        page = self.client.post(reverse("quizzes:teacher_ai"), {
            "action": "generate", "niveau": self.lesson.course.niveau, "lesson": self.lesson.pk,
            "question_count": 2, "difficulty": "moyen",
        })
        self.assertEqual(page.status_code, 200)
        self.assertIsNone(page.context["error"])
        quiz = Quiz.objects.get()
        self.assertEqual(list(quiz.questions.order_by("order").values_list("text", flat=True)),
                         [self.good["text"], self.fixed["text"]])
        for q in quiz.questions.all():
            self.assertEqual(q.choices.count(), 4)
            self.assertEqual(q.choices.filter(is_correct=True).count(), 1)
            self.assertEqual(q.correct_answer, q.choices.get(is_correct=True).text)

    def test_fenced_json_and_latex_repairs_still_pass_final_validation(self):
        raw = r'''```json
        {"quiz":{"questions":[{"question":"Calculer $\frac{1}{2}$",
          "choices":["$\frac{1}{2}$","1"], "correct_answer":"$\frac{1}{2}$"}]}}
        ```'''
        result = self.service._validate_quiz_json(raw, 1)
        self.assertEqual(result["questions"][0]["correct_answer"], r"$\frac{1}{2}$")
