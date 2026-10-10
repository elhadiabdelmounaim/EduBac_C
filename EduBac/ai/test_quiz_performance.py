"""Performance invariants and quality regressions; no live/paid AI calls."""
import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from education.media_library import chapter_relative, source_files_for_lessons
from education.models import Course, Lesson
from quizzes.generation import save_generated_quiz
from quizzes.models import Choice, Quiz, QuizGenerationQuestion
from .providers import AIProviderError
from .quiz_novelty import reserve_questions, signature, validate_local
from .services import AIService
from .test_quiz_validation import question, response


@override_settings(QUIZ_SEMANTIC_CHECK_ENABLED=False)
class QuizPerformanceTests(TestCase):
    def setUp(self):
        self.course = Course.objects.create(name="Mathématiques", niveau="tronc_commun")
        self.lesson = Lesson.objects.create(course=self.course, title="Algèbre", order=1, content="Cours " * 600)
        self.provider = patch.object(AIService, "_get_provider",
                                     return_value=SimpleNamespace(name="groq", model="test"))
        self.provider.start()
        self.addCleanup(self.provider.stop)
        self.service = AIService()

    def test_source_catalogue_has_no_query_per_lesson_and_stays_fresh(self):
        other_course = Course.objects.create(name="Autre cours", niveau="tronc_commun", order=2)
        other = Lesson.objects.create(course=other_course, title="Algèbre", order=1)
        lessons = list(Lesson.objects.select_related("course").order_by("pk"))
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            folder = Path(directory) / chapter_relative(other) / "Sources_IA"
            folder.mkdir(parents=True)
            (folder / "premier.txt").write_text("Cours", encoding="utf-8")
            with self.assertNumQueries(0):
                result = source_files_for_lessons(lessons)
            self.assertEqual(result[str(other.pk)], ["premier.txt"])
            self.assertEqual(result[str(self.lesson.pk)], [])
            (folder / "nouveau.txt").write_text("Cours modifié", encoding="utf-8")
            with self.assertNumQueries(0):
                self.assertEqual(source_files_for_lessons(lessons)[str(other.pk)],
                                 ["nouveau.txt", "premier.txt"])

    def test_each_history_signature_is_computed_once(self):
        history = [question(f"Notion notion{chr(97+i)}.") for i in range(20)]
        new = [question("Une situation géométrique originale.")]
        with patch("ai.quiz_novelty.signature", wraps=signature) as hashed:
            validate_local(new, history)
        self.assertEqual(hashed.call_count, len(history) + len(new))

    @override_settings(QUIZ_SEMANTIC_CHECK_ENABLED=True)
    def test_concurrent_history_review_runs_outside_reservation_transaction(self):
        old = question("Ancienne situation de factorisation.")
        new = question("Nouvelle situation de géométrie.")
        QuizGenerationQuestion.objects.create(lesson=self.lesson, signature=signature(old), data=old)
        outer_depth = len(connection.atomic_blocks)

        def review(service, candidates, history):
            self.assertEqual(len(connection.atomic_blocks), outer_depth)
            self.assertEqual(history, [old])

        with patch("ai.quiz_novelty.validate_semantic", side_effect=review) as reviewed:
            reserve_questions(self.service, self.lesson, [new], [])
        reviewed.assert_called_once()
        self.assertEqual(QuizGenerationQuestion.objects.count(), 2)

    def test_grouped_save_has_three_inserts_and_preserves_math_and_order(self):
        items = [question(f"Situation notion{chr(97+i)} : $x^2$.") for i in range(5)]
        with CaptureQueriesContext(connection) as queries:
            quiz = save_generated_quiz({"questions": items}, title="Quiz", lesson=self.lesson)
        inserts = [query for query in queries if query["sql"].lstrip().upper().startswith("INSERT")]
        self.assertEqual(len(inserts), 3)
        self.assertEqual(quiz.question_count, 5)
        self.assertEqual(list(quiz.questions.order_by("order").values_list("text", flat=True)),
                         [item["text"] for item in items])
        self.assertEqual(Choice.objects.filter(question__quiz=quiz).count(), 20)
        self.assertEqual(Choice.objects.filter(question__quiz=quiz, is_correct=True).count(), 5)

    def test_failed_choice_insert_rolls_back_entire_quiz(self):
        with patch("quizzes.generation.Choice.objects.bulk_create", side_effect=ValueError("Erreur simulée")):
            with self.assertRaises(ValueError):
                save_generated_quiz({"questions": [question()]}, title="Quiz", lesson=self.lesson)
        self.assertFalse(Quiz.objects.exists())

    @patch.object(AIService, "_chat")
    def test_twenty_questions_use_token_aware_batches_without_partial_persistence(self, chat):
        all_questions = []

        def generate(messages, **kwargs):
            count = int(re.search(r"Nombre de questions EXACT : (\d+)", messages[1]["content"])[1])
            self.assertGreaterEqual(kwargs["max_tokens"], count * 400)
            self.assertLessEqual(kwargs["max_tokens"], 7500)
            self.assertFalse(QuizGenerationQuestion.objects.exists())
            items = [question(f"Situation notion{chr(97+len(all_questions)+index)}.")
                     for index in range(count)]
            all_questions.extend(items)
            return response(*items)

        chat.side_effect = generate
        result = self.service.generate_quiz_from_lesson(self.lesson, 20)
        self.assertEqual(result["questions"], all_questions)
        self.assertEqual(len(result["questions"]), 20)
        self.assertGreater(chat.call_count, 1)
        self.assertEqual(QuizGenerationQuestion.objects.count(), 20)

    @patch.object(AIService, "_chat")
    def test_second_generation_batch_failure_never_reserves_partial_quiz(self, chat):
        def generate(messages, **kwargs):
            if chat.call_count == 2:
                raise AIProviderError("Timeout simulé", code="timeout")
            count = int(re.search(r"Nombre de questions EXACT : (\d+)", messages[1]["content"])[1])
            return response(*(question(f"Situation notion{chr(97+i)}.") for i in range(count)))
        chat.side_effect = generate
        with self.assertRaises(AIProviderError):
            self.service.generate_quiz_from_lesson(self.lesson, 20)
        self.assertFalse(QuizGenerationQuestion.objects.exists())

    @patch.object(AIService, "_chat")
    def test_oversized_instructions_fail_explicitly_before_any_api_call(self, chat):
        with self.assertRaises(AIProviderError):
            self.service.generate_quiz_from_lesson(self.lesson, 1, description="Objectif " * 4000)
        chat.assert_not_called()

    @patch.object(AIService, "_chat")
    def test_partial_batch_repair_preserves_valid_slots_and_only_replaces_remaining(self, chat):
        good, fixed = question(), question("Exprimer une aire de triangle.")
        other = question("Comparer deux fractions.")
        broken = {"text": "Énoncé incomplet"}
        bad_other = dict(broken, text="Autre énoncé incomplet")
        chat.side_effect = [
            response(broken, good, bad_other),
            response(dict(fixed, index=1), dict(bad_other, index=3)),
            response(dict(other, index=3)),
        ]
        result = self.service.generate_quiz_from_lesson(self.lesson, 3)
        self.assertEqual(result["questions"], [fixed, good, other])
        payload = json.loads(chat.call_args_list[2].args[0][-1]["content"].split("\n", 1)[1])
        self.assertEqual([entry["index"] for entry in payload["invalides"]], [3])
        self.assertEqual(chat.call_count, 3)

    @patch.object(AIService, "_chat")
    def test_duplicate_or_missing_repair_indexes_fail_closed(self, chat):
        broken = {"text": "Question sans choix"}
        chat.side_effect = [response(broken, broken),
                            response(dict(question(), index=1), dict(question(), index=1)),
                            response(dict(question(), index=1))]
        with self.assertRaises(AIProviderError) as error:
            self.service.generate_quiz_from_lesson(self.lesson, 2)
        self.assertEqual(error.exception.code, "invalid_question")
        self.assertFalse(QuizGenerationQuestion.objects.exists())

    @patch.object(AIService, "_chat")
    def test_quiz_prompt_is_specialized_and_shorter_than_previous_system_prompt(self, chat):
        chat.return_value = response(question())
        self.service.generate_quiz_from_lesson(self.lesson, 1, use_resources=False)
        messages = chat.call_args.args[0]
        self.assertLess(len(messages[0]["content"]), len(AIService.SYSTEM_PROMPT))
        self.assertNotIn("synthese", messages[0]["content"])
        self.assertIn("Mode sans ressources", messages[1]["content"])
        self.assertNotIn('"level":', messages[1]["content"])
