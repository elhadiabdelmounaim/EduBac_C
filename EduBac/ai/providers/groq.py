"""Provider Groq (modèles gratuits / rapides)."""
from __future__ import annotations

import logging

from django.conf import settings

from .base import AIProviderError, BaseProvider

logger = logging.getLogger(__name__)


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
            self._client = Groq(api_key=self.api_key)
        return self._client

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> str:
        self.ensure_configured()
        try:
            from groq import APIError, APIConnectionError, RateLimitError
        except ImportError:
            APIError = APIConnectionError = RateLimitError = Exception  # type: ignore

        client = self._get_client()
        models_to_try = [self.model] + [m for m in self.FALLBACK_MODELS if m != self.model]
        last_error = None

        for model_id in models_to_try:
            try:
                kwargs = {
                    "model": model_id,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}
                response = client.chat.completions.create(**kwargs)
                if model_id != self.model:
                    logger.warning("Groq: modèle %s indisponible, fallback %s", self.model, model_id)
                return response.choices[0].message.content or ""
            except RateLimitError as e:
                raise AIProviderError(f"Rate limit Groq : {e}", code="rate_limit") from e
            except APIConnectionError as e:
                raise AIProviderError(f"Connexion Groq impossible : {e}", code="connection") from e
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
