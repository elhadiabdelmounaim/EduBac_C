import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import TeacherProfile, User
from education.models import Course, Lesson
from quizzes.models import Question, Quiz, QuizGenerationQuestion
from .providers import AIProviderError
from .quiz_novelty import (
    QuizNoveltyError, canonical_question, history_instruction, previous_questions,
    quiz_output_budget, reserve_questions, similarity, validate_local, validate_semantic,
)
from .services import AIService


OLD = [
    "Développer et réduire $(x+3)^2$.",
    "Déterminer le discriminant de $x^2-5x+6=0$.",
]
NEW = [
    "Une parcelle rectangulaire a pour côtés $(x+1)$ et $(x-2)$. "
    "Exprimer son aire sous forme polynomiale.",
    "Sans résoudre l’équation, décider si $x^2+4x+8=0$ possède des solutions réelles "
    "et justifier à l’aide du signe du discriminant.",
]


def quiz_json(texts):
    return json.dumps({
        "title": "Quiz varié",
        "questions": [{
            "text": text,
            "choices": [{"text": str(index), "is_correct": index == 0} for index in range(4)],
            "correct_answer": "0", "explanation": "Raisonnement lié à la question.", "hint": "Relis la règle.",
        } for text in texts],
    })


@override_settings(ALLOWED_HOSTS=["testserver"], QUIZ_SEMANTIC_CHECK_ENABLED=True)
class QuizNoveltyTests(TestCase):
    def setUp(self):
        self.course = Course.objects.create(name="Algèbre", niveau="tronc_commun")
        self.lesson = Lesson.objects.create(
            title="Polynômes", course=self.course,
            content="Développer, factoriser, utiliser les identités remarquables et le discriminant.",
        )
        self.service = AIService()
        self.provider = patch.object(AIService, "_get_provider", return_value=SimpleNamespace(
            name="test", model="test-model",
        ))
        self.provider.start()
        self.addCleanup(self.provider.stop)
        self.sleep = patch("ai.services.time.sleep")
        self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def history(self, texts=OLD, lesson=None):
        quiz = Quiz.objects.create(title="Ancien quiz", lesson=lesson or self.lesson)
        for index, text in enumerate(texts):
            Question.objects.create(quiz=quiz, text=text, explanation="Méthode précédente.", order=index)
        return quiz

    def test_numbers_variable_names_and_delimiters_do_not_create_novelty(self):
        self.assertEqual(canonical_question(r"Développer \((x+3)^2\)."),
                         canonical_question(r"Développer $(t+12)^2$."))
        self.assertGreaterEqual(similarity("Calculer la dérivée de $x^2+3x$.",
                                          "Calculer la dérivée de $t^2+8t$."), 0.86)

    @patch.object(AIService, "_chat")
    def test_shared_wording_with_different_reasoning_reaches_semantic_review(self, chat):
        old = "Calculer la dérivée de la fonction $f(x)=x^2+3x$."
        new = "Calculer une primitive de la fonction $f(x)=x^2+3x$."
        self.assertGreater(similarity(old, new), 0.86)
        self.history([old])
        chat.side_effect = [quiz_json([new]), '{"similar_questions":[]}']
        result = self.service.generate_quiz_from_lesson(self.lesson, 1)
        self.assertEqual(result["questions"][0]["text"], new)
        self.assertEqual(chat.call_count, 2)
        self.assertEqual(QuizGenerationQuestion.objects.count(), 1)

    @patch.object(AIService, "_chat")
    def test_similar_wording_still_rejected_by_semantic_review(self, chat):
        old = "Calculer la dérivée de la fonction $f(x)=x^2+3x$."
        new = "Déterminer la dérivée de la fonction $f(x)=x^2+3x$."
        self.assertGreater(similarity(old, new), 0.86)
        self.history([old])
        chat.side_effect = [quiz_json([new]), '{"similar_questions":[1]}'] * 3
        with self.assertRaises(AIProviderError) as error:
            self.service.generate_quiz_from_lesson(self.lesson, 1)
        self.assertEqual(error.exception.code, "duplicate_questions")
        self.assertEqual(QuizGenerationQuestion.objects.count(), 0)

    def test_history_prompt_keeps_three_short_examples(self):
        history = [{"text": f"Question numéro {i} " + ("x" * 200)} for i in range(6)]
        sample = json.loads(history_instruction(history).split("données) :\n", 1)[1])
        self.assertEqual([item["text"][:18] for item in sample], [
            "Question numéro 3 ", "Question numéro 4 ", "Question numéro 5 ",
        ])
        self.assertTrue(all(len(item["text"]) == 150 for item in sample))

    @override_settings(QUIZ_SEMANTIC_CHECK_ENABLED=False)
    @patch.object(AIService, "_chat")
    def test_semantic_model_call_stays_off_unless_enabled(self, chat):
        self.history([OLD[0]])
        chat.return_value = quiz_json([NEW[0]])
        data = self.service.generate_quiz_from_lesson(self.lesson, 1)
        self.assertEqual(data["questions"][0]["text"], NEW[0])
        self.assertEqual(chat.call_count, 1)

    @patch.object(AIService, "_chat")
    def test_generation_caps_the_question_count_at_twenty(self, chat):
        chat.return_value = quiz_json([NEW[0]])
        with self.assertRaises(AIProviderError):
            self.service.generate_quiz_from_lesson(self.lesson, 25)
        prompt = chat.call_args_list[0].args[0][1]["content"]
        self.assertIn("Nombre de questions EXACT : 20", prompt)

    def test_ai_help_prefers_the_summary_inside_the_character_budget(self):
        lesson = Lesson.objects.create(
            title="Longue leçon",
            content="C" * 8000,
            summary="RESUME IMPORTANT",
            course=self.course,
        )
        contenu = lesson.get_ai_help()["contenu"]
        self.assertLessEqual(len(contenu), 5000)
        self.assertTrue(contenu.startswith("## Resume"))
        self.assertIn("RESUME IMPORTANT", contenu)
        self.assertTrue(contenu.endswith("[... contenu tronque ...]"))

    def test_groq_output_budget_accounts_for_prompt_and_question_count(self):
        messages = [{"role": "user", "content": "a" * 6000}]
        self.assertEqual(quiz_output_budget(20, messages, "groq"), 5200)
        self.assertEqual(quiz_output_budget(2, messages, "groq"), 800)
        self.assertEqual(quiz_output_budget(20, messages, "other-provider"), 8000)
        self.assertLessEqual(quiz_output_budget(20, messages, "groq"), 5200)

    @patch.object(AIService, "_chat")
    def test_reordered_quiz_is_rejected_then_replaced(self, chat):
        self.history()
        chat.side_effect = [quiz_json(list(reversed(OLD))), quiz_json(NEW),
                            '{"similar_questions":[]}']
        result = self.service.generate_quiz_from_lesson(self.lesson, 2, description="Deux notions variées")
        self.assertEqual([q["text"] for q in result["questions"]], NEW)
        self.assertEqual(QuizGenerationQuestion.objects.count(), 2)
        self.assertEqual(chat.call_count, 3)
        self.assertIn("REFUSÉ", chat.call_args_list[1].args[0][-1]["content"])

    @patch.object(AIService, "_chat")
    def test_number_only_variants_are_rejected(self, chat):
        self.history([OLD[0]])
        chat.return_value = quiz_json(["Développer et réduire $(t+17)^2$."])
        with self.assertRaises(AIProviderError) as error:
            self.service.generate_quiz_from_lesson(self.lesson, 1)
        self.assertEqual(error.exception.code, "duplicate_questions")
        self.assertEqual(QuizGenerationQuestion.objects.count(), 0)

    @patch.object(AIService, "_chat")
    def test_same_question_with_other_choices_is_rejected(self, chat):
        self.history([OLD[0]])
        changed = json.loads(quiz_json([OLD[0]]))
        changed["questions"][0]["choices"].reverse()
        chat.return_value = json.dumps(changed)
        with self.assertRaises(AIProviderError):
            self.service.generate_quiz_from_lesson(self.lesson, 1)
        self.assertEqual(QuizGenerationQuestion.objects.count(), 0)

    @patch.object(AIService, "_chat")
    def test_internal_near_duplicate_is_rejected_without_history(self, chat):
        chat.return_value = quiz_json([OLD[0], "Développer et réduire $(t+15)^2$."])
        with self.assertRaises(AIProviderError):
            self.service.generate_quiz_from_lesson(self.lesson, 2)
        self.assertEqual(QuizGenerationQuestion.objects.count(), 0)

    @patch.object(AIService, "_chat")
    def test_semantic_rephrasing_is_reviewed_and_replaced(self, chat):
        self.history([OLD[0]])
        rephrased = "Quelle écriture polynomiale correspond au carré de la somme de $x$ et de $7$ ?"
        self.assertLess(similarity(rephrased, OLD[0]), 0.86)
        chat.side_effect = [quiz_json([rephrased]), '{"similar_questions":[1]}',
                            quiz_json([NEW[0]]), '{"similar_questions":[]}']
        data = self.service.generate_quiz_from_lesson(self.lesson, 1)
        self.assertEqual(data["questions"][0]["text"], NEW[0])
        comparison = json.loads(chat.call_args_list[1].args[0][-1]["content"])
        self.assertEqual(comparison["previous_questions"][0]["text"], OLD[0])

    @patch.object(AIService, "_chat")
    def test_generator_service_remembers_previews_without_a_quiz_record(self, chat):
        chat.return_value = quiz_json([OLD[0]])
        self.service.generate_quiz_from_lesson(self.lesson, 1)
        self.assertEqual(Quiz.objects.count(), 0)
        self.assertEqual(QuizGenerationQuestion.objects.count(), 1)
        chat.side_effect = [quiz_json([OLD[0]]), quiz_json([NEW[0]]), '{"similar_questions":[]}']
        result = AIService().generate_quiz_from_lesson(self.lesson, 1)
        self.assertEqual(result["questions"][0]["text"], NEW[0])
        self.assertEqual(QuizGenerationQuestion.objects.count(), 2)

    def test_entire_older_history_is_compared_not_just_prompt_sample(self):
        self.history([OLD[0]] + [
            f"Autre question archivée archive{chr(97 + i // 26)}{chr(97 + i % 26)}" for i in range(40)
        ])
        with self.assertRaises(QuizNoveltyError):
            validate_local([{"text": OLD[0]}], previous_questions(self.lesson))

    @patch.object(AIService, "_chat")
    def test_history_is_lesson_scoped(self, chat):
        other = Lesson.objects.create(title="Autre cours", course=self.course, content="Autre leçon")
        self.history([OLD[0]], lesson=other)
        chat.return_value = quiz_json([OLD[0]])
        result = self.service.generate_quiz_from_lesson(self.lesson, 1)
        self.assertEqual(result["questions"][0]["text"], OLD[0])
        self.assertEqual(chat.call_count, 1)

    @patch.object(AIService, "_chat")
    def test_uncertain_semantic_verdict_fails_closed(self, chat):
        self.history([OLD[0]])
        chat.side_effect = [quiz_json([NEW[0]]), '{"similar_questions":"unknown"}'] * 3
        with self.assertRaises(AIProviderError) as error:
            self.service.generate_quiz_from_lesson(self.lesson, 1)
        self.assertEqual(error.exception.code, "novelty_validation_failed")
        self.assertEqual(QuizGenerationQuestion.objects.count(), 0)

    @patch.object(AIService, "_chat")
    def test_exact_question_count_is_preserved(self, chat):
        chat.return_value = quiz_json([NEW[0]])
        with self.assertRaises(AIProviderError):
            self.service.generate_quiz_from_lesson(self.lesson, 3)
        self.assertEqual(QuizGenerationQuestion.objects.count(), 0)

    @patch.object(AIService, "_chat")
    def test_prompt_preserves_parameters_and_adds_history_and_request_identifier(self, chat):
        self.history([OLD[0]])
        chat.side_effect = [quiz_json([NEW[0]]), '{"similar_questions":[]}']
        self.service.generate_quiz_from_lesson(
            self.lesson, 1, "difficile", description="Applications géométriques des polynômes",
        )
        prompt = chat.call_args_list[0].args[0][1]["content"]
        for value in (self.lesson.title, "difficile", "Nombre de questions EXACT : 1",
                      "Applications géométriques des polynômes", OLD[0], "DIVERSITÉ OBLIGATOIRE",
                      "Identifiant de cette nouvelle demande"):
            self.assertIn(value, prompt)

    @patch.object(AIService, "_chat", return_value='{"similar_questions":[]}')
    def test_semantic_check_covers_all_history_in_batches(self, chat):
        history = [{"text": f"Ancienne question archive{i}", "explanation": ""} for i in range(51)]
        validate_semantic(self.service, [{"text": NEW[0]}], history)
        self.assertEqual(chat.call_count, 3)
        reviewed = []
        for call in chat.call_args_list:
            reviewed.extend(json.loads(call.args[0][-1]["content"])["previous_questions"])
        self.assertEqual([q["text"] for q in reviewed], [q["text"] for q in history])

    @patch.object(AIService, "_chat")
    def test_provider_json_mode_failure_uses_validated_plain_json(self, chat):
        chat.side_effect = [AIProviderError("json_validate_failed", code="api_error"),
                            quiz_json([OLD[0]])]
        data = self.service.generate_quiz_from_lesson(self.lesson, 1)
        self.assertEqual(data["questions"][0]["text"], OLD[0])
        self.assertTrue(chat.call_args_list[0].kwargs["json_mode"])
        self.assertFalse(chat.call_args_list[1].kwargs["json_mode"])
        self.assertLess(chat.call_args_list[0].kwargs["max_tokens"], 8000)

    @patch.object(AIService, "_chat")
    def test_openrouter_json_mode_rejection_retries_plain_json(self, chat):
        chat.side_effect = [
            AIProviderError(
                "OpenRouter HTTP 404 : No endpoints found that support response_format json_object",
                code="not_found",
            ),
            quiz_json([OLD[0]]),
        ]
        data = self.service.generate_quiz_from_lesson(self.lesson, 1)
        self.assertEqual(data["questions"][0]["text"], OLD[0])
        self.assertFalse(chat.call_args_list[1].kwargs["json_mode"])

    @patch.object(AIService, "_chat")
    def test_rate_limit_is_not_retried_as_plain_json(self, chat):
        chat.side_effect = AIProviderError("Limite atteinte", code="rate_limit")
        with self.assertRaises(AIProviderError) as error:
            self.service.generate_quiz_from_lesson(self.lesson, 1)
        self.assertEqual(error.exception.code, "rate_limit")
        self.assertEqual(chat.call_count, 1)

    @patch.object(AIService, "_chat")
    def test_semantic_plain_json_fallback_is_still_checked(self, chat):
        self.history([OLD[0]])
        chat.side_effect = [
            quiz_json([NEW[0]]), AIProviderError("json_validate_failed", code="api_error"),
            '```json\n{"similar_questions":[]}\n```',
        ]
        data = self.service.generate_quiz_from_lesson(self.lesson, 1)
        self.assertEqual(data["questions"][0]["text"], NEW[0])
        self.assertFalse(chat.call_args_list[2].kwargs["json_mode"])

    @patch.object(AIService, "_chat", return_value='{"similar_questions":[]}')
    def test_large_quiz_review_is_bounded_and_covers_cross_batch_pairs(self, chat):
        new = [{"text": f"Nouvel exercice {i}", "explanation": "Raisonnement " * 70}
               for i in range(12)]
        history = [{"text": f"Ancien exercice {i}", "explanation": "Situation " * 100}
                   for i in range(28)]
        validate_semantic(self.service, new, history)
        covered = set()
        for call in chat.call_args_list:
            payload = json.loads(call.args[0][-1]["content"])
            self.assertLessEqual(len(call.args[0][-1]["content"]), 14000)
            for current in payload["new_questions"]:
                covered.update((current["index"], old["text"]) for old in payload["previous_questions"])
            if payload["compare_new_questions"]:
                for index, current in enumerate(payload["new_questions"]):
                    covered.update((current["index"], old["text"])
                                   for old in payload["new_questions"][:index])
        for index in range(1, 13):
            for old in history + new[:index - 1]:
                self.assertIn((index, old["text"]), covered)

    def test_final_reservation_rechecks_concurrent_history(self):
        # Another request reserved this question after our initial history read.
        reserve_questions(self.service, self.lesson, [{"text": OLD[0]}], [])
        with self.assertRaises(QuizNoveltyError):
            reserve_questions(self.service, self.lesson, [{"text": OLD[0]}], [])
        self.assertEqual(QuizGenerationQuestion.objects.count(), 1)

    @patch.object(AIService, "_chat")
    def test_teacher_clicks_save_two_different_quizzes_with_same_parameters(self, chat):
        teacher = User.objects.create_user(
            username="novelty-teacher", email="novelty@example.test", role="teacher",
        )
        TeacherProfile.objects.get_or_create(user=teacher)
        session = self.client.session
        session["user_id"] = teacher.pk
        session.save()
        params = {"action": "generate", "niveau": self.course.niveau, "lesson": self.lesson.pk,
                  "question_count": 2, "seconds_per_question": 35, "difficulty": "difficile",
                  "description": "Varier les raisonnements sur les polynômes"}
        chat.side_effect = [quiz_json(OLD), '{"similar_questions":[]}',
                            quiz_json(list(reversed(OLD))), quiz_json(NEW), '{"similar_questions":[]}']
        for _ in range(2):
            response = self.client.post(reverse("quizzes:teacher_ai"), params)
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(response.context["error"])
            self.assertRegex(response.content.decode(), r'name="question_count"[^>]+value="2"')
            self.assertRegex(response.content.decode(), r'name="seconds_per_question"[^>]+value="35"')
            self.assertContains(response, '<option value="difficile" selected>')
            self.assertContains(response, 'data-manual="1"')
        quizzes = list(Quiz.objects.order_by("pk"))
        self.assertEqual(len(quizzes), 2)
        self.assertEqual(list(quizzes[0].questions.order_by("order").values_list("text", flat=True)), OLD)
        self.assertEqual(list(quizzes[1].questions.order_by("order").values_list("text", flat=True)), NEW)
        for quiz in quizzes:
            self.assertEqual(quiz.question_count, 2)
            self.assertEqual(quiz.seconds_per_question, 35)
            self.assertEqual(quiz.difficulty, "difficile")
            self.assertEqual(quiz.description, params["description"])

    @patch.object(AIService, "_chat")
    def test_teacher_duplicate_failure_does_not_create_a_quiz(self, chat):
        self.history()
        teacher = User.objects.create_user(
            username="novelty-refused", email="novelty-refused@example.test", role="teacher",
        )
        session = self.client.session
        session["user_id"] = teacher.pk
        session.save()
        chat.return_value = quiz_json(OLD)
        before = Quiz.objects.count()
        response = self.client.post(reverse("quizzes:teacher_ai"), {
            "action": "generate", "niveau": self.course.niveau, "lesson": self.lesson.pk,
            "question_count": 2, "difficulty": "moyen", "description": "Conserver le sujet",
        })
        self.assertContains(response, "Aucun quiz dupliqué")
        self.assertEqual(Quiz.objects.count(), before)
        self.assertEqual(response.context["quiz_description"], "Conserver le sujet")
