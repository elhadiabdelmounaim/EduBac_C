"""Provider OpenAI (API officielle, compatible chat completions)."""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

from .base import AIProviderError, BaseProvider

logger = logging.getLogger(__name__)

OPENAI_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIProvider(BaseProvider):
    name = "openai"
    display_name = "OpenAI"

    def __init__(self, api_key: str = "", model: str = "", **kwargs):
        api_key = api_key or getattr(settings, "OPENAI_API_KEY", "")
        model = model or getattr(settings, "OPENAI_MODEL", "gpt-4o-mini")
        super().__init__(api_key=api_key, model=model, **kwargs)

    def list_models(self):
        return [
            {"id": "gpt-4o-mini", "label": "GPT-4o Mini (économique)"},
            {"id": "gpt-4o", "label": "GPT-4o"},
            {"id": "gpt-4.1-mini", "label": "GPT-4.1 Mini"},
            {"id": "gpt-4.1", "label": "GPT-4.1"},
            {"id": "o4-mini", "label": "o4-mini (raisonnement)"},
        ]

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> str:
        self.ensure_configured()
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            OPENAI_URL,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace") if e.fp else str(e)
            code = "rate_limit" if e.code == 429 else "api_error"
            if e.code in (401, 403):
                code = "missing_api_key"
            raise AIProviderError(
                f"OpenAI HTTP {e.code} : {raw[:300]}",
                code=code,
            ) from e
        except urllib.error.URLError as e:
            raise AIProviderError(
                f"Connexion OpenAI impossible : {e.reason}",
                code="connection",
            ) from e
        except TimeoutError as e:
            raise AIProviderError("Timeout OpenAI.", code="timeout") from e
        except Exception as e:
            raise AIProviderError(f"Erreur OpenAI : {e}", code="unknown") from e

        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise AIProviderError(
                f"Réponse OpenAI invalide : {data!r}"[:400],
                code="invalid_response",
            ) from e
