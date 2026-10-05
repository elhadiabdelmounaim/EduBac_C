"""Provider OpenRouter (modèles gratuits via API compatible OpenAI)."""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

from .base import AIProviderError, BaseProvider

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterProvider(BaseProvider):
    name = "openrouter"
    display_name = "OpenRouter"

    def __init__(self, api_key: str = "", model: str = "", **kwargs):
        api_key = api_key or getattr(settings, "OPENROUTER_API_KEY", "")
        model = model or getattr(
            settings, "OPENROUTER_MODEL", "openrouter/free"
        )
        super().__init__(api_key=api_key, model=model, **kwargs)
        self.site_url = getattr(settings, "SITE_URL", "http://localhost")
        self.app_name = "EduBac"

    def list_models(self):
        return [
            {"id": "openrouter/free", "label": "OpenRouter Free (auto)"},
            {"id": "meta-llama/llama-3.1-8b-instruct:free", "label": "Llama 3.1 8B Free"},
            {"id": "google/gemma-2-9b-it:free", "label": "Gemma 2 9B Free"},
            {"id": "mistralai/mistral-7b-instruct:free", "label": "Mistral 7B Free"},
            {"id": "qwen/qwen-2.5-7b-instruct:free", "label": "Qwen 2.5 7B Free"},
            {"id": "deepseek/deepseek-r1-distill-llama-70b:free", "label": "DeepSeek R1 Distill Free"},
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
            OPENROUTER_URL,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": self.site_url,
                "X-Title": self.app_name,
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
                f"OpenRouter HTTP {e.code} : {raw[:300]}",
                code=code,
            ) from e
        except urllib.error.URLError as e:
            raise AIProviderError(
                f"Connexion OpenRouter impossible : {e.reason}",
                code="connection",
            ) from e
        except TimeoutError as e:
            raise AIProviderError("Timeout OpenRouter.", code="timeout") from e
        except Exception as e:
            raise AIProviderError(f"Erreur OpenRouter : {e}", code="unknown") from e

        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise AIProviderError(
                f"Réponse OpenRouter invalide : {data!r}"[:400],
                code="invalid_response",
            ) from e
