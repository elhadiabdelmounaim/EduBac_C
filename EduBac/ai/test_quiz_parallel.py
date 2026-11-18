import threading
import time
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from .providers import AIProviderError
from .quiz_parallel import run_parallel


@override_settings(QUIZ_PARALLEL_WORKERS=3)
class RunParallelTests(SimpleTestCase):
    def test_results_keep_task_order_and_overlap_in_time(self):
        seen = set()

        def task(value, delay):
            def run():
                seen.add(threading.get_ident())
                time.sleep(delay)
                return value
            return run

        started = time.monotonic()
        results = run_parallel([task("a", 0.3), task("b", 0.1), task("c", 0.2)])
        self.assertEqual(results, ["a", "b", "c"])
        self.assertLess(time.monotonic() - started, 0.55)  # sequential would be ~0.6s
        self.assertGreater(len(seen), 1)

    def test_single_task_runs_inline(self):
        main = threading.get_ident()
        self.assertEqual(run_parallel([lambda: threading.get_ident()]), [main])

    @override_settings(QUIZ_PARALLEL_WORKERS=1)
    def test_one_worker_is_sequential(self):
        main = threading.get_ident()
        self.assertEqual(run_parallel([lambda: threading.get_ident()] * 3), [main] * 3)

    def test_rate_limit_is_retried_sequentially(self):
        calls = []

        def limited():
            calls.append(threading.get_ident())
            if len(calls) == 1:
                raise AIProviderError("429", code="rate_limit")
            return "ok"

        self.assertEqual(run_parallel([limited, lambda: "fine"]), ["ok", "fine"])
        self.assertEqual(calls[-1], threading.get_ident())

    def test_other_errors_propagate_in_task_order(self):
        def boom():
            raise AIProviderError("bad", code="bad_request")

        with self.assertRaises(AIProviderError) as ctx:
            run_parallel([lambda: 1, boom, lambda: 3])
        self.assertEqual(ctx.exception.code, "bad_request")
