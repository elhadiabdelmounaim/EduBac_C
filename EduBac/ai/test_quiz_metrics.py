import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from .quiz_metrics import GenerationTrace, current_trace
from .quiz_protocol import analyze_context
from .quiz_quota import _windows, observe, reserve, release
from .providers.groq import GroqProvider
from .providers import AIProviderError
from .services import AIService
from .quiz_arithmetic import constant_value


class QuizInstrumentationTests(SimpleTestCase):
    def setUp(self):
        _windows.clear()
        self.addCleanup(_windows.clear)

    def test_quota_reservations_share_a_window_and_release_without_unbounded_wait(self):
        with patch("ai.quiz_quota.time.monotonic", return_value=100):
            observe("test-model", 8000, 500, 56.25)
            first, delay = reserve("test-model", 1200, 800, 30)
            self.assertIsNotNone(first)
            self.assertAlmostEqual(delay, 7.85)
            second, second_delay = reserve("test-model", 1200, 800, 30)
            self.assertGreater(second_delay, delay)
            release("test-model", first)
            release("test-model", second)
            self.assertEqual(reserve("test-model", 1200, 800, 1), (None, 0))
            self.assertEqual(reserve("test-model", 50000, 800, 30), (None, 0))

    def test_absent_or_invalid_headers_do_not_introduce_delay(self):
        self.assertEqual(reserve("unknown", 1000, 800, 30), (None, 0))
        observe("invalid", 8000, 9000, 10)
        self.assertNotIn("invalid", _windows)

    def test_constant_checker_is_exact_bounded_and_never_executes_code(self):
        from fractions import Fraction
        self.assertEqual(constant_value(r"\frac{1}{3}+\frac{1}{6}"), Fraction(1, 2))
        self.assertEqual(constant_value("4(1+3+3^2+3^3+3^4)"), 484)
        for unsupported in ("__import__('os').system('false')", "x+1", "2^1000000",
                            "2^(2^12)", "1/0", "f(1)", "9" * 501):
            self.assertIsNone(constant_value(unsupported))

    def test_provider_measures_http_headers_and_usage_not_first_generated_token(self):
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok":true}', reasoning=None))],
            usage=SimpleNamespace(prompt_tokens=20, completion_tokens=10, total_tokens=30),
        )
        raw = SimpleNamespace(
            headers={"x-ratelimit-limit-tokens": "8000",
                     "x-ratelimit-remaining-tokens": "7000", "x-ratelimit-reset-tokens": "7.5s"},
            parse=lambda: response,
        )
        create = Mock(return_value=nullcontext(raw))
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            with_streaming_response=SimpleNamespace(create=create))))
        provider = GroqProvider(api_key="test-placeholder", model="test-model")
        trace = GenerationTrace()
        token = current_trace.set(trace)
        try:
            with patch.object(provider, "_get_client", return_value=client):
                self.assertEqual(provider.chat([{"role": "user", "content": "JSON"}]), '{"ok":true}')
        finally:
            current_trace.reset(token)
        self.assertEqual(trace.usage["total_tokens"], 30)
        self.assertEqual(trace.counts["provider_requests"], 1)
        self.assertIn("http_headers_ms", trace.last_response)
        self.assertNotIn("first_token_ms", trace.last_response)

    @patch.object(AIService, "_chat")
    def test_analysis_uses_reference_ids_without_copying_sources_twice(self, chat):
        source = "Définition : addition.\nExemple : Calculer $2+3$."
        service = AIService()
        chat.return_value = json.dumps({
            "compatible": True, "reason": "Sujet compatible.", "skills": ["Additionner"],
            "reference_segments": [2],
        })
        with patch.object(service, "_get_provider", return_value=SimpleNamespace(name="test")):
            result = analyze_context(service, {"contenu": source, "niveau": "Tronc Commun"},
                                     "Calculs", related_knowledge=True, difficulty="moyen", count=1)
        self.assertIn("Calculer $2+3$.", result["reference_questions"])
        payload = json.loads(chat.call_args.args[0][1]["content"])
        self.assertNotIn("contenu", payload["context"])
        self.assertEqual(payload["source_segments"][1]["text"], "Exemple : Calculer $2+3$.")
        self.assertEqual(chat.call_args.kwargs["max_tokens"], 1000)

    @patch.object(AIService, "_chat")
    def test_invalid_reference_id_stops_before_generation(self, chat):
        chat.return_value = json.dumps({
            "compatible": True, "reason": "Compatible.", "skills": ["Calculer"],
            "reference_segments": [True],
        })
        service = AIService()
        with patch.object(service, "_get_provider", return_value=SimpleNamespace(name="test")):
            with self.assertRaises(AIProviderError):
                analyze_context(service, {"contenu": "Calculer $2+3$."}, "Calculs",
                                related_knowledge=True, difficulty="moyen", count=1)
