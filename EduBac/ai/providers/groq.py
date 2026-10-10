"""Provider Groq (modèles gratuits / rapides)."""
from __future__ import annotations

import json
import logging
import time
import re

from django.conf import settings

from .base import AIProviderError, BaseProvider, http_error_code

logger = logging.getLogger(__name__)

_RETRY_AFTER_CLOCK = re.compile(
    r"try again in\s+(?:(\d+)m\s*)?(\d+(?:\.\d+)?)(ms|s)\b",
    re.IGNORECASE,
)


def _seconds_from_retry_text(text: str) -> float | None:
    """Parse Groq hints such as ``20.6s``, ``597ms`` and ``9m57s``."""
    match = _RETRY_AFTER_CLOCK.search(text or "")
    if not match:
        return None
    minutes = int(match.group(1) or 0)
    amount = float(match.group(2))
    if match.group(3).lower() == "ms":
        amount /= 1000.0
    return minutes * 60 + amount


def _retry_after_seconds(exc) -> float | None:
    """Read Groq's wait hint. A millisecond value must not become minutes."""
    from_text = _seconds_from_retry_text(str(exc))
    from_header = None
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is not None:
        raw_ms = headers.get("retry-after-ms")
        if raw_ms:
            try:
                from_header = float(raw_ms) / 1000.0
            except (TypeError, ValueError):
                from_header = None
        if from_header is None:
            raw = headers.get("retry-after")
            if raw:
                try:
                    from_header = float(raw)
                except (TypeError, ValueError):
                    from_header = None
    if from_text is None:
        return from_header
    if from_header is None:
        return from_text
    # Header and body sometimes disagree by 1000x (ms read as s, or the reverse).
    if from_header > from_text * 10 or from_text > from_header * 10:
        return from_text
    return from_header


# One quiz retry may wait for Groq. A longer TPM window is shown to the teacher.
GROQ_RATE_LIMIT_MAX_WAIT = 30.0


def bounded_retry_after(delay: float | None, *, max_wait: float = GROQ_RATE_LIMIT_MAX_WAIT) -> float | None:
    """Return the wait before a single retry, or None when Groq asks for longer."""
    if delay is None:
        return None
    try:
        delay = float(delay)
    except (TypeError, ValueError):
        return None
    if delay <= 0 or delay > max_wait:
        return None
    return delay


def _reasoning_effort_for(model_id: str) -> str | None:
    """Keep completion tokens for the quiz JSON. gpt-oss rejects effort ``none``."""
    model_id = model_id or ""
    if model_id.startswith("openai/gpt-oss"):
        return "low"
    if model_id.startswith("qwen/"):
        return "none"
    return None


def _error_blob(exc) -> str:
    parts = [str(exc)]
    body = getattr(exc, "body", None)
    if body is not None:
        parts.append(str(body))
    return " ".join(parts).lower()


def _failed_generation_text(exc) -> str | None:
    """Groq JSON mode returns the rejected text instead of the completion."""
    body = getattr(exc, "body", None)
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            return None
    if not isinstance(body, dict):
        return None
    error = body.get("error")
    if not isinstance(error, dict):
        return None
    failed = error.get("failed_generation")
    if not isinstance(failed, str) or "{" not in failed:
        return None
    if "questions" not in failed and '"text"' not in failed:
        return None
    return failed


def _assistant_text(message) -> str:
    """Prefer the answer. gpt-oss often leaves the JSON in ``reasoning``."""
    content = getattr(message, "content", None) or ""
    reasoning = getattr(message, "reasoning", None) or ""
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                parts.append(str(part.get("text") or ""))
        content = "".join(parts)
    content = str(content)
    reasoning = str(reasoning)
    if "{" in content:
        return content
    if "{" in reasoning:
        return reasoning
    return content or reasoning


class GroqProvider(BaseProvider):
    name = "groq"
    display_name = "Groq"

    # Llama 3.1 8B Instant and Llama 3.3 70B were removed from Groq free and
    # developer tiers. 404 falls through to a model this key can still call.
    FALLBACK_MODELS = [
        "openai/gpt-oss-20b",
        "qwen/qwen3.8-27b",
        "openai/gpt-oss-120b",
    ]

    def __init__(self, api_key: str = "", model: str = "", **kwargs):
        api_key = api_key or getattr(settings, "GROQ_API_KEY", "")
        # gpt-oss reasoning tokens count toward TPM. The chat call asks for low effort.
        model = model or getattr(settings, "GROQ_MODEL", "openai/gpt-oss-20b")
        super().__init__(api_key=api_key, model=model, **kwargs)
        self._client = None

    def list_models(self):
        return [
            {"id": "openai/gpt-oss-20b", "label": "GPT-OSS 20B"},
            {"id": "qwen/qwen3.8-27b", "label": "Qwen 3.8 27B"},
            {"id": "openai/gpt-oss-120b", "label": "GPT-OSS 120B"},
        ]

    def _get_client(self):
        if self._client is None:
            try:
                from groq import Groq
            except ImportError as e:
                raise AIProviderError(
                    "Package 'groq' non installé. pip install groq",
                    code="missing_package",
                ) from e
            # max_retries=0: the quiz service decides whether to retry.
            # The SDK default (2) can stack 60s timeouts before Django sees an error.
            self._client = Groq(api_key=self.api_key, timeout=self.timeout, max_retries=0)
        return self._client

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        json_mode: bool = False,
        timeout: float | None = None,
    ) -> str:
        self.ensure_configured()
        try:
            from groq import APIConnectionError, APIError, APIStatusError, APITimeoutError, RateLimitError
        except ImportError:
            APIError = APIConnectionError = APIStatusError = APITimeoutError = RateLimitError = Exception  # type: ignore

        client = self._get_client()
        models_to_try = [self.model] + [m for m in self.FALLBACK_MODELS if m != self.model]
        last_error = None
        call_timeout = self.timeout if timeout is None else timeout
        deadline = time.monotonic() + call_timeout

        for model_id in models_to_try:
            kwargs = {
                "model": model_id,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "timeout": call_timeout,
            }
            effort = _reasoning_effort_for(model_id)
            if effort:
                kwargs["reasoning_effort"] = effort
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            dropped_effort = False
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AIProviderError("Timeout Groq.", code="timeout")
                kwargs["timeout"] = remaining
                try:
                    response = client.chat.completions.create(**kwargs)
                    if model_id != self.model:
                        logger.warning(
                            "Groq: modèle %s non utilisé, réponse via %s", self.model, model_id,
                        )
                    return _assistant_text(response.choices[0].message)
                except RateLimitError as e:
                    # Keep the configured GROQ_MODEL. A silent switch would ignore
                    # the model selected in the environment.
                    logger.warning(
                        "generate_quiz API error: Groq rate limit model=%s retry_after=%s",
                        model_id, _retry_after_seconds(e),
                    )
                    raise AIProviderError(
                        f"Rate limit Groq : {e}",
                        code="rate_limit",
                        retry_after=_retry_after_seconds(e),
                    ) from e
                except APITimeoutError as e:
                    raise AIProviderError("Timeout Groq.", code="timeout") from e
                except APIConnectionError as e:
                    raise AIProviderError(f"Connexion Groq impossible : {e}", code="connection") from e
                except APIStatusError as e:
                    err = _error_blob(e)
                    status = getattr(e, "status_code", 0) or 0
                    if (
                        status == 400
                        and not dropped_effort
                        and kwargs.get("reasoning_effort")
                        and "reasoning_effort" in err
                        and "json_validate_failed" not in err
                    ):
                        kwargs.pop("reasoning_effort", None)
                        dropped_effort = True
                        logger.warning(
                            "generate_quiz API error: Groq rejected reasoning_effort model=%s",
                            model_id,
                        )
                        continue
                    failed = _failed_generation_text(e)
                    if status == 400 and failed and (
                        "json_validate_failed" in err or "failed_generation" in err
                    ):
                        logger.warning(
                            "generate_quiz API error: Groq JSON invalide, texte récupéré model=%s",
                            model_id,
                        )
                        if model_id != self.model:
                            logger.warning(
                                "Groq: modèle %s non utilisé, réponse via %s",
                                self.model, model_id,
                            )
                        return failed
                    if (
                        status == 404
                        or "model_not_found" in err
                        or "does not exist" in err
                        or "not have access" in err
                    ):
                        last_error = e
                        logger.warning("Groq modèle indisponible: %s", model_id)
                        break
                    raise AIProviderError(
                        f"Erreur API Groq ({status}) : {e}",
                        code=http_error_code(status),
                    ) from e
                except APIError as e:
                    err = _error_blob(e)
                    if "model_not_found" in err or "does not exist" in err or "not have access" in err:
                        last_error = e
                        logger.warning("Groq modèle indisponible: %s", model_id)
                        break
                    raise AIProviderError(f"Erreur API Groq : {e}", code="api_error") from e
                except Exception as e:
                    raise AIProviderError(f"Erreur Groq : {e}", code="unknown") from e

        raise AIProviderError(
            f"Aucun modèle Groq disponible. Dernière erreur : {last_error}",
            code="model_unavailable",
        )
