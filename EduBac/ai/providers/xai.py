"""Provider xAI Grok (API compatible OpenAI)."""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

from .base import AIProviderError, BaseProvider, http_error_code

logger = logging.getLogger(__name__)

XAI_URL = "https://api.x.ai/v1/chat/completions"


class XAIProvider(BaseProvider):
    name = "xai"
    display_name = "xAI Grok"

    def __init__(self, api_key: str = "", model: str = "", **kwargs):
        api_key = api_key or getattr(settings, "XAI_API_KEY", "")
        model = model or getattr(settings, "XAI_MODEL", "grok-3-mini")
        super().__init__(api_key=api_key, model=model, **kwargs)

    def list_models(self):
        return [
            {"id": "grok-3-mini", "label": "Grok 3 Mini"},
            {"id": "grok-3", "label": "Grok 3"},
            {"id": "grok-2", "label": "Grok 2"},
            {"id": "grok-2-mini", "label": "Grok 2 Mini"},
        ]

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
            XAI_URL,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        call_timeout = self.timeout if timeout is None else timeout
        try:
            with urllib.request.urlopen(req, timeout=call_timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace") if e.fp else str(e)
            raise AIProviderError(
                f"xAI Grok HTTP {e.code} : {raw[:300]}",
                code=http_error_code(e.code),
            ) from e
        except urllib.error.URLError as e:
            if isinstance(getattr(e, "reason", None), TimeoutError):
                raise AIProviderError("Timeout xAI Grok.", code="timeout") from e
            raise AIProviderError(
                f"Connexion xAI impossible : {e.reason}",
                code="connection",
            ) from e
        except TimeoutError as e:
            raise AIProviderError("Timeout xAI Grok.", code="timeout") from e
        except Exception as e:
            raise AIProviderError(f"Erreur xAI Grok : {e}", code="unknown") from e

        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise AIProviderError(
                f"Réponse xAI invalide : {data!r}"[:400],
                code="invalid_response",
            ) from e
