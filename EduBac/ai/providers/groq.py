"""Provider Groq (modèles gratuits / rapides)."""
from __future__ import annotations

import logging
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


class GroqProvider(BaseProvider):
    name = "groq"
    display_name = "Groq"

    FALLBACK_MODELS = [
        "llama-3.1-8b-instant",
        "llama-3.3-70b-versatile",
        "openai/gpt-oss-20b",
        "openai/gpt-oss-120b",
    ]

    def __init__(self, api_key: str = "", model: str = "", **kwargs):
        api_key = api_key or getattr(settings, "GROQ_API_KEY", "")
        model = model or getattr(settings, "GROQ_MODEL", "llama-3.1-8b-instant")
        super().__init__(api_key=api_key, model=model, **kwargs)
        self._client = None

    def list_models(self):
        return [
            {"id": "llama-3.1-8b-instant", "label": "Llama 3.1 8B Instant"},
            {"id": "llama-3.3-70b-versatile", "label": "Llama 3.3 70B Versatile"},
            {"id": "openai/gpt-oss-20b", "label": "GPT-OSS 20B"},
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

        for model_id in models_to_try:
            try:
                kwargs = {
                    "model": model_id,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "timeout": call_timeout,
                }
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}
                response = client.chat.completions.create(**kwargs)
                if model_id != self.model:
                    logger.warning("Groq: modèle %s non utilisé, réponse via %s", self.model, model_id)
                return response.choices[0].message.content or ""
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
                err = str(e).lower()
                status = getattr(e, "status_code", 0) or 0
                if status == 404 or "model_not_found" in err or "does not exist" in err or "not have access" in err:
                    last_error = e
                    logger.warning("Groq modèle indisponible: %s", model_id)
                    continue
                raise AIProviderError(
                    f"Erreur API Groq ({status}) : {e}",
                    code=http_error_code(status),
                ) from e
            except APIError as e:
                err = str(e).lower()
                if "model_not_found" in err or "does not exist" in err or "not have access" in err:
                    last_error = e
                    logger.warning("Groq modèle indisponible: %s", model_id)
                    continue
                raise AIProviderError(f"Erreur API Groq : {e}", code="api_error") from e
            except Exception as e:
                raise AIProviderError(f"Erreur Groq : {e}", code="unknown") from e

        raise AIProviderError(
            f"Aucun modèle Groq disponible. Dernière erreur : {last_error}",
            code="model_unavailable",
        )
