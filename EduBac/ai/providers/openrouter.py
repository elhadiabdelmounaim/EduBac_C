"""Provider OpenRouter (modèles gratuits via API compatible OpenAI)."""
from __future__ import annotations

import json
import logging
import time

from django.conf import settings

from .base import AIProviderError, BaseProvider, http_error_code
from .http_json import post_json

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# The free auto-router often stalls when forced onto a JSON-mode endpoint.
_ROUTER_MODELS = frozenset({"openrouter/free", "openrouter/auto"})


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

    def _router_model(self) -> bool:
        return self.model.strip().lower() in _ROUTER_MODELS

    def _exchange(self, payload: dict, deadline: float) -> tuple[int, str]:
        remaining = deadline - time.monotonic()
        if remaining < 0.5:
            raise TimeoutError("timed out")
        return post_json(
            OPENROUTER_URL,
            json.dumps(payload).encode("utf-8"),
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": self.site_url,
                "X-Title": self.app_name,
            },
            remaining,
        )

    @staticmethod
    def _without_rejected_options(payload: dict, raw: str) -> dict | None:
        """Drop optional fields OpenRouter refused, so the quiz can still be generated."""
        text = raw.lower()
        trimmed = dict(payload)
        changed = False
        if "response_format" in trimmed and any(
            token in text for token in ("response_format", "json_object", "json mode", "structured")
        ):
            trimmed.pop("response_format")
            changed = True
        if "reasoning" in trimmed and "reasoning" in text:
            trimmed.pop("reasoning")
            changed = True
        if "provider" in trimmed and any(token in text for token in ("provider", "sort", "throughput")):
            trimmed.pop("provider")
            changed = True
        return trimmed if changed else None

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
        call_timeout = self.timeout if timeout is None else timeout
        deadline = time.monotonic() + call_timeout
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        # A bounded quiz call must spend its tokens on the answer. The free
        # router otherwise queues a reasoning model and outlives the page.
        if timeout is not None:
            payload["reasoning"] = {"effort": "none"}
            payload["provider"] = {"sort": "throughput"}
        if json_mode and not self._router_model():
            payload["response_format"] = {"type": "json_object"}

        try:
            status, raw = self._exchange(payload, deadline)
            if status == 400:
                trimmed = self._without_rejected_options(payload, raw)
                if trimmed is not None:
                    logger.warning(
                        "generate_quiz API error: OpenRouter rejected optional fields, retrying model=%s",
                        self.model,
                    )
                    status, raw = self._exchange(trimmed, deadline)
            if status in (408, 504):
                raise AIProviderError(
                    f"Timeout OpenRouter ({status}).",
                    code="timeout",
                )
            if status >= 400:
                raise AIProviderError(
                    f"OpenRouter HTTP {status} : {raw[:300]}",
                    code=http_error_code(status),
                )
            data = json.loads(raw)
        except AIProviderError:
            raise
        except TimeoutError as e:
            logger.warning(
                "generate_quiz API error: OpenRouter timeout model=%s", self.model,
            )
            raise AIProviderError("Timeout OpenRouter.", code="timeout") from e
        except OSError as e:
            raise AIProviderError(
                f"Connexion OpenRouter impossible : {e}",
                code="connection",
            ) from e
        except json.JSONDecodeError as e:
            raise AIProviderError(
                f"Réponse OpenRouter invalide : {raw[:300]!r}",
                code="invalid_response",
            ) from e
        except Exception as e:
            raise AIProviderError(f"Erreur OpenRouter : {e}", code="unknown") from e

        try:
            message = data["choices"][0]["message"] or {}
            content = message.get("content") or ""
            if not str(content).strip():
                content = message.get("reasoning") or message.get("reasoning_content") or ""
            if not str(content).strip():
                raise KeyError("content")
            return str(content)
        except (KeyError, IndexError, TypeError) as e:
            raise AIProviderError(
                f"Réponse OpenRouter invalide : {data!r}"[:400],
                code="invalid_response",
            ) from e
