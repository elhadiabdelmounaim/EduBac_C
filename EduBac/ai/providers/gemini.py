"""Provider Google Gemini (free tier) via REST API."""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

from .base import AIProviderError, BaseProvider, http_error_code

logger = logging.getLogger(__name__)

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider(BaseProvider):
    name = "gemini"
    display_name = "Gemini"

    def __init__(self, api_key: str = "", model: str = "", **kwargs):
        api_key = api_key or getattr(settings, "GEMINI_API_KEY", "")
        model = model or getattr(settings, "GEMINI_MODEL", "gemini-2.0-flash")
        super().__init__(api_key=api_key, model=model, **kwargs)

    def list_models(self):
        return [
            {"id": "gemini-2.0-flash", "label": "Gemini 2.0 Flash"},
            {"id": "gemini-2.0-flash-lite", "label": "Gemini 2.0 Flash Lite"},
            {"id": "gemini-1.5-flash", "label": "Gemini 1.5 Flash"},
            {"id": "gemini-1.5-flash-8b", "label": "Gemini 1.5 Flash 8B"},
        ]

    def _messages_to_gemini(self, messages: list[dict[str, str]]):
        """Convertit messages OpenAI-style → contents Gemini + systemInstruction."""
        system_parts = []
        contents = []
        for m in messages:
            role = m.get("role", "user")
            text = m.get("content") or ""
            if role == "system":
                system_parts.append(text)
            elif role == "assistant":
                contents.append({"role": "model", "parts": [{"text": text}]})
            else:
                contents.append({"role": "user", "parts": [{"text": text}]})
        system_instruction = None
        if system_parts:
            system_instruction = {"parts": [{"text": "\n\n".join(system_parts)}]}
        return contents, system_instruction

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
        contents, system_instruction = self._messages_to_gemini(messages)

        generation_config = {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        }
        if json_mode:
            generation_config["responseMimeType"] = "application/json"

        payload: dict = {
            "contents": contents,
            "generationConfig": generation_config,
        }
        if system_instruction:
            payload["systemInstruction"] = system_instruction

        model_id = self.model
        if model_id.startswith("models/"):
            model_id = model_id[len("models/") :]

        url = (
            f"{GEMINI_BASE}/{urllib.parse.quote(model_id, safe='')}:generateContent"
            f"?key={urllib.parse.quote(self.api_key)}"
        )
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        call_timeout = self.timeout if timeout is None else timeout
        try:
            with urllib.request.urlopen(req, timeout=call_timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace") if e.fp else str(e)
            code = http_error_code(e.code)
            if e.code in (400, 401, 403) and ("API key" in raw or "API_KEY" in raw):
                code = "missing_api_key"
            raise AIProviderError(
                f"Gemini HTTP {e.code} : {raw[:300]}",
                code=code,
            ) from e
        except urllib.error.URLError as e:
            if isinstance(getattr(e, "reason", None), TimeoutError):
                raise AIProviderError("Timeout Gemini.", code="timeout") from e
            raise AIProviderError(
                f"Connexion Gemini impossible : {e.reason}",
                code="connection",
            ) from e
        except TimeoutError as e:
            raise AIProviderError("Timeout Gemini.", code="timeout") from e
        except Exception as e:
            raise AIProviderError(f"Erreur Gemini : {e}", code="unknown") from e

        try:
            candidates = data.get("candidates") or []
            if not candidates:
                # blocked / empty
                feedback = data.get("promptFeedback") or data
                raise AIProviderError(
                    f"Gemini n'a renvoyé aucune réponse : {feedback!r}"[:400],
                    code="empty_response",
                )
            parts = candidates[0]["content"]["parts"]
            texts = [p.get("text", "") for p in parts if "text" in p]
            return "\n".join(texts).strip()
        except AIProviderError:
            raise
        except (KeyError, IndexError, TypeError) as e:
            raise AIProviderError(
                f"Réponse Gemini invalide : {data!r}"[:400],
                code="invalid_response",
            ) from e
