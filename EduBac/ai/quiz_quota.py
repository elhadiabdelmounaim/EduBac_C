"""Best-effort, thread-safe pacing from observed Groq token-window headers.

No API keys, prompts or answers are stored. Windows are local to this process;
other workers/account clients can still consume quota, so 429 recovery remains required.
"""
import math
import threading
import time
import uuid

_lock = threading.Lock()
_windows = {}


def observe(model, limit, remaining, reset_seconds):
    if (not all(math.isfinite(n) for n in (limit, remaining, reset_seconds))
            or limit <= 0 or not 0 <= remaining <= limit or reset_seconds <= 0):
        return
    with _lock:
        pending = _windows.get(model, {}).get("pending", {})
        _windows[model] = {
            "limit": limit, "remaining": remaining, "at": time.monotonic(),
            "rate": (limit - remaining) / reset_seconds, "pending": pending,
        }


def reserve(model, input_chars, output_tokens, max_wait):
    """Reserve only when a recent, usable window fits the request's deadline."""
    needed = input_chars // 3 + 300 + output_tokens
    with _lock:
        window = _windows.get(model)
        now = time.monotonic()
        if (window is None or now - window["at"] > 120
                or window["rate"] <= 0 or needed > window["limit"]):
            return None, 0
        available = min(window["limit"], window["remaining"] + (now - window["at"]) * window["rate"])
        available -= sum(window["pending"].values())
        delay = max(0, (needed - available) / window["rate"])
        if delay:
            delay += 0.35
        if delay > max_wait:
            return None, 0  # Let the provider return its authoritative error, never sleep indefinitely.
        token = uuid.uuid4().hex
        window["pending"][token] = needed
        return token, delay


def release(model, token):
    with _lock:
        if model in _windows:
            _windows[model]["pending"].pop(token, None)
