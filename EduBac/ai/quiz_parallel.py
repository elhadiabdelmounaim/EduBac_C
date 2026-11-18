"""Run independent AI review calls concurrently, with a sequential safety net.

Only used for checks whose calls do not depend on each other. Results always come
back in the order of the tasks, and the first error (in task order) is re-raised.
"""
import logging
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings

from .providers import AIProviderError

logger = logging.getLogger(__name__)


def parallel_workers() -> int:
    return max(1, int(getattr(settings, "QUIZ_PARALLEL_WORKERS", 3)))


def _run_in_worker(task):
    # Workers have no generation trace (it lives in a ContextVar), so they never
    # write progress rows from another thread; the caller's phase still times them.
    try:
        return task()
    finally:
        from django.db import connections
        connections.close_all()


def run_parallel(tasks):
    """Return [task() for task in tasks], executed concurrently when useful."""
    tasks = list(tasks)
    workers = min(parallel_workers(), len(tasks))
    if workers <= 1:
        return [task() for task in tasks]
    outcomes = []
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="quiz-review") as pool:
        futures = [pool.submit(_run_in_worker, task) for task in tasks]
        for future in futures:
            try:
                outcomes.append((True, future.result()))
            except Exception as exc:  # re-examined below, in task order
                outcomes.append((False, exc))
    results = []
    for task, (ok, value) in zip(tasks, outcomes):
        if ok:
            results.append(value)
            continue
        if isinstance(value, AIProviderError) and value.code == "rate_limit":
            # Concurrency may have caused the 429: retry alone, where the
            # service's bounded quota wait applies.
            logger.warning("quiz_parallel rate limit, retrying sequentially")
            results.append(task())
            continue
        raise value
    return results
