"""OpenRouter quiz calls must finish or fail before the browser gives up."""
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from django.test import SimpleTestCase

from .providers import AIProviderError
from .providers.http_json import address_order, post_json
from .providers.openrouter import OpenRouterProvider
from .services import AIService, public_quiz_error


class _QuietHandler(BaseHTTPRequestHandler):
    delay = 0

    def do_POST(self):
        time.sleep(self.delay)
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return


def _server(delay):
    handler = type("Handler", (_QuietHandler,), {"delay": delay})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


class OpenRouterTimeoutTests(SimpleTestCase):
    def test_ipv4_is_attempted_before_ipv6(self):
        ordered = address_order([
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 80, 0, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80)),
        ])
        self.assertEqual(ordered[0][0], socket.AF_INET)

    def test_post_returns_a_local_json_body(self):
        httpd = _server(0)
        try:
            port = httpd.server_address[1]
            status, text = post_json(
                f"http://127.0.0.1:{port}/v1",
                b"{}",
                {"Content-Type": "application/json"},
                2,
            )
        finally:
            httpd.shutdown()
            httpd.server_close()
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(text), {"ok": True})

    def test_post_stops_at_the_wall_clock_timeout(self):
        httpd = _server(3)
        started = time.monotonic()
        try:
            port = httpd.server_address[1]
            with self.assertRaises(TimeoutError):
                post_json(
                    f"http://127.0.0.1:{port}/v1",
                    b"{}",
                    {"Content-Type": "application/json"},
                    0.4,
                )
        finally:
            httpd.shutdown()
            httpd.server_close()
        self.assertLess(time.monotonic() - started, 2)

    def test_quiz_call_uses_one_budget_and_skips_json_mode_on_the_free_router(self):
        provider = OpenRouterProvider(api_key="test-key", model="openrouter/free")
        service = AIService(provider="openrouter", model="openrouter/free")
        service._quiz_deadline = time.monotonic() + 10
        seen = {}

        def fake_post(url, body, headers, timeout):
            seen["url"] = url
            seen["body"] = json.loads(body.decode())
            seen["timeout"] = timeout
            seen["auth"] = headers["Authorization"]
            return 200, json.dumps({
                "choices": [{"message": {"content": "{\"questions\":[]}"}}],
            })

        with (
            patch.object(service, "_get_provider", return_value=provider),
            patch("ai.providers.openrouter.post_json", side_effect=fake_post),
        ):
            text = service._chat(
                [{"role": "user", "content": "quiz"}],
                json_mode=True,
            )

        self.assertEqual(text, "{\"questions\":[]}")
        self.assertNotIn("response_format", seen["body"])
        self.assertEqual(seen["body"]["model"], "openrouter/free")
        self.assertEqual(seen["body"]["reasoning"], {"effort": "none"})
        self.assertEqual(seen["body"]["provider"], {"sort": "throughput"})
        self.assertLessEqual(seen["timeout"], 10)
        self.assertEqual(seen["auth"], "Bearer test-key")
        self.assertNotIn("sk-", seen["body"].get("messages", [{}])[-1]["content"])

    def test_named_model_keeps_json_mode_and_retries_without_rejected_options(self):
        provider = OpenRouterProvider(api_key="test-key", model="meta-llama/llama-3.1-8b-instruct")
        calls = []

        def fake_post(url, body, headers, timeout):
            payload = json.loads(body.decode())
            calls.append(payload)
            if len(calls) == 1:
                return 400, '{"error":"reasoning is not supported and provider sort is unknown"}'
            return 200, json.dumps({
                "choices": [{"message": {"content": "", "reasoning": "{\"ok\":true}"}}],
            })

        with patch("ai.providers.openrouter.post_json", side_effect=fake_post):
            text = provider.chat(
                [{"role": "user", "content": "quiz"}],
                json_mode=True,
                timeout=8,
            )

        self.assertEqual(text, "{\"ok\":true}")
        self.assertEqual(calls[0]["response_format"], {"type": "json_object"})
        self.assertNotIn("reasoning", calls[1])
        self.assertNotIn("provider", calls[1])
        self.assertEqual(calls[1]["response_format"], {"type": "json_object"})

    def test_timeout_becomes_a_quiz_error_without_another_model(self):
        provider = OpenRouterProvider(api_key="test-key", model="openrouter/free")

        def fake_post(url, body, headers, timeout):
            raise TimeoutError("timed out")

        with patch("ai.providers.openrouter.post_json", side_effect=fake_post):
            with self.assertRaises(AIProviderError) as error:
                provider.chat([{"role": "user", "content": "quiz"}], timeout=5)

        self.assertEqual(error.exception.code, "timeout")
        self.assertIn("trop de temps", public_quiz_error(error.exception))
