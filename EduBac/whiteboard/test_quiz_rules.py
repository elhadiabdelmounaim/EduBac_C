import json
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import User
from education.models import Course, Lesson
from education.templatetags.markdown_extras import latex_only
from quizzes.models import Attempt, Question, Quiz, StudentAnswer
from .models import QuizCorrectionBoard
from .rule_service import generate_rule_document


RULE = {
    "name": "Identité remarquable",
    "statement": "Cette identité permet de développer le carré d’une somme de deux termes.",
    "latex": r"(a+b)^2 = a^2 + 2ab + b^2",
}


@override_settings(ALLOWED_HOSTS=["testserver"])
class QuizRuleBoardTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            username="rule-student", email="rule@test.local", role="student",
        )
        course = Course.objects.create(name="Algèbre", niveau="tronc_commun")
        lesson = Lesson.objects.create(course=course, title="Identités", content="Identités remarquables")
        self.quiz = Quiz.objects.create(title="Identités", lesson=lesson)
        self.question = Question.objects.create(
            quiz=self.quiz, text="Développer $(x+3)^2$", correct_answer="$x^2+6x+9$",
            explanation="Identité remarquable : $$(a+b)^2 = a^2 + 2ab + b^2$$\n"
                        "Étape 1 : remplacer b par 3.\nÉtape 2 : développer.",
        )
        self.attempt = Attempt.objects.create(
            student=self.student, quiz=self.quiz, submitted_at=timezone.now(), score=100,
        )
        self.answer = StudentAnswer.objects.create(
            attempt=self.attempt, question=self.question, answer="$x^2+6x+9$", is_correct=True,
        )
        self.page = f"/tableau/correction/{self.attempt.pk}/{self.question.pk}/"
        self.api = self.page + "api/"
        self.legacy = {
            "version": 1, "title": "Correction",
            "elements": [{"id": f"step{i}", "type": "step", "text": f"Ancienne étape {i}"}
                         for i in range(1, 6)],
            "connections": [],
        }
        self.board = QuizCorrectionBoard.objects.create(
            attempt=self.attempt, question=self.question, data=self.legacy, revision=8,
        )
        session = self.client.session
        session["user_id"] = self.student.pk
        session.save()

    def post(self, data):
        return self.client.post(self.api, json.dumps(data), content_type="application/json")

    def test_open_discards_every_old_element_and_invalidates_stale_saves(self):
        response = self.client.get(self.page)
        self.assertContains(response, 'data-rule-only="1"')
        self.assertNotContains(response, "Correction complète")
        self.board.refresh_from_db()
        self.assertEqual(self.board.data, {})
        self.assertEqual(self.board.revision, 9)
        stale = self.post({"action": "save", "revision": 8, "document": self.legacy})
        self.assertEqual(stale.status_code, 409)
        self.board.refresh_from_db()
        self.assertEqual(self.board.data, {})

    @patch("ai.services.AIService._chat", return_value=json.dumps(RULE))
    def test_auto_generation_returns_only_rule_and_reuses_explanation_filter(self, chat):
        self.client.get(self.page)
        response = self.post({"action": "generate"}).json()
        document = response["document"]
        self.assertEqual(len(document["elements"]), 1)
        self.assertEqual(document["elements"][0]["type"], "rule")
        self.assertEqual(document["connections"], [])
        text = document["elements"][0]["text"]
        self.assertEqual(text, "Identité remarquable\n$$(a+b)^2 = a^2 + 2ab + b^2$$\n"
                              + RULE["statement"])
        self.assertEqual(response["rendered_rules"]["rule1"]["html"], str(latex_only(text)))
        self.assertNotIn("Étape", json.dumps(document, ensure_ascii=False))
        self.assertNotIn("x^2+6x+9", json.dumps(document))
        messages = chat.call_args.args[0]
        self.assertIn("ni étapes", messages[0]["content"])
        self.assertIn(self.question.explanation, json.loads(messages[1]["content"])["explanation"])
        self.attempt.refresh_from_db()
        self.answer.refresh_from_db()
        self.assertEqual(self.attempt.score, 100)
        self.assertEqual(self.answer.answer, "$x^2+6x+9$")

    @patch("ai.services.AIService._chat", return_value=json.dumps(RULE))
    def test_legacy_cache_is_not_exposed_or_reused(self, chat):
        self.assertFalse(self.client.get(self.api).json()["exists"])
        response = self.post({"action": "generate"}).json()
        self.assertFalse(response["cached"])
        self.assertEqual(response["document"]["elements"][0]["type"], "rule")
        chat.assert_called_once()
        cached = self.post({"action": "generate"}).json()
        self.assertTrue(cached["cached"])
        self.assertIn("rule1", cached["rendered_rules"])
        self.client.get(self.page)
        self.board.refresh_from_db()
        self.assertEqual(self.board.data, {})
        self.post({"action": "generate"})
        self.assertEqual(chat.call_count, 2)

    @patch("ai.services.AIService._chat", side_effect=RuntimeError("Provider unavailable"))
    def test_provider_failure_stays_empty_and_can_retry(self, chat):
        self.client.get(self.page)
        for _ in range(2):
            data = self.post({"action": "generate"}).json()
            self.assertEqual(data["document"]["elements"], [])
            self.assertTrue(data["warning"])
            self.assertFalse(data["generated_by_ai"])
        self.assertEqual(chat.call_count, 2)
        self.board.refresh_from_db()
        self.assertEqual(self.board.data["elements"], [])

    @patch("ai.services.AIService._chat", return_value=json.dumps({"elements": [{"type": "step"}]}))
    def test_model_cannot_return_a_full_correction_document(self, chat):
        data = self.post({"action": "generate"}).json()
        self.assertEqual(data["document"]["elements"], [])

    @patch("ai.services.AIService._chat", return_value=json.dumps(RULE))
    def test_saved_steps_and_chat_solutions_are_rejected(self, chat):
        self.client.get(self.page)
        data = self.post({"action": "generate"}).json()
        response = self.post({"action": "save", "revision": data["revision"], "document": self.legacy})
        self.assertEqual(response.status_code, 400)
        saved = self.post({"action": "save", "revision": data["revision"], "document": data["document"]})
        self.assertEqual(saved.status_code, 200)
        self.assertIn("rule1", saved.json()["rendered_rules"])
        self.assertEqual(self.post({"action": "chat", "message": "Donne cinq étapes"}).status_code, 400)

    def test_other_student_cannot_clear_the_board(self):
        other = User.objects.create_user(username="other-rule", email="other@test.local", role="student")
        session = self.client.session
        session["user_id"] = other.pk
        session.save()
        self.assertEqual(self.client.get(self.page).status_code, 404)
        self.assertEqual(self.post({"action": "generate"}).status_code, 404)
        self.board.refresh_from_db()
        self.assertEqual(self.board.data, self.legacy)

    @patch("whiteboard.correction_views.generate_correction_document")
    def test_unfinished_quiz_preserves_hint_flow(self, generate):
        self.attempt.submitted_at = None
        self.attempt.save()
        self.client.get(self.page)
        self.board.refresh_from_db()
        self.assertEqual(self.board.data, self.legacy)
        generate.return_value = ({"version": 1, "title": "Indice", "elements": [], "connections": []},
                                 False, "")
        self.post({"action": "generate", "regenerate": True})
        self.assertEqual(generate.call_args.kwargs["mode"], "hint")
        self.assertIsNone(generate.call_args.kwargs["good_answer"])

    @patch("ai.services.AIService._chat")
    def test_delimiter_normalization_and_safe_html(self, chat):
        chat.return_value = json.dumps(dict(RULE, name="Propriété <b>générale</b>",
                                           latex=r"\[(a+b)^2 = a^2 + 2ab + b^2\]"))
        data = self.post({"action": "generate"}).json()
        html = data["rendered_rules"]["rule1"]["html"]
        self.assertIn("&lt;b&gt;", html)
        self.assertIn("$$(a+b)^2 = a^2 + 2ab + b^2$$", html)
        self.assertNotIn("<b>", html)

    @patch("ai.services.AIService._chat")
    def test_long_or_multiline_rule_is_rejected_without_steps(self, chat):
        chat.return_value = json.dumps(dict(RULE, statement="Étape 1\nÉtape 2"))
        document, by_ai, warning = generate_rule_document({"explanation": self.question.explanation})
        self.assertEqual(document["elements"], [])
        self.assertFalse(by_ai)
        self.assertTrue(warning)

    @patch("ai.services.AIService._chat")
    def test_formula_is_not_duplicated_in_plain_text(self, chat):
        chat.return_value = json.dumps(dict(RULE, statement=RULE["latex"]))
        document, by_ai, warning = generate_rule_document({})
        self.assertFalse(by_ai)
        self.assertEqual(document["elements"], [])
        self.assertTrue(warning)

    @patch("ai.services.AIService._chat")
    def test_rule_includes_short_explanation_after_formula(self, chat):
        chat.return_value = json.dumps(RULE)
        document, by_ai, warning = generate_rule_document({})
        self.assertTrue(by_ai)
        text = document["elements"][0]["text"]
        self.assertTrue(text.endswith(RULE["statement"]))
        self.assertLess(text.index("$$"), text.index(RULE["statement"]))

    @patch("ai.services.AIService._chat")
    def test_rule_is_dynamic_for_a_different_question(self, chat):
        rule = {"name": "Théorème de Pythagore", "latex": "c^2 = a^2 + b^2",
                "statement": "Dans un triangle rectangle, cette relation permet de calculer une longueur."}
        chat.return_value = json.dumps(rule)
        document, by_ai, warning = generate_rule_document({
            "question_text": "Calculer l’hypoténuse d’un triangle rectangle.",
            "explanation": "Appliquer le théorème de Pythagore.",
        })
        self.assertTrue(by_ai)
        text = document["elements"][0]["text"]
        self.assertIn("Pythagore", text)
        self.assertIn("$$c^2 = a^2 + b^2$$", text)
        self.assertNotIn("Identité remarquable", text)
