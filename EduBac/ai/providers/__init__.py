"""
Registre des fournisseurs IA.
Ajouter un nouveau provider = 1 fichier + 1 entrée dans PROVIDERS.
Le Quiz Generator appelle uniquement get_provider() / list_providers().
"""
from __future__ import annotations

from typing import Type

from .base import AIProviderError, BaseProvider
from .gemini import GeminiProvider
from .groq import GroqProvider
from .openai_provider import OpenAIProvider
from .openrouter import OpenRouterProvider
from .xai import XAIProvider

PROVIDERS: dict[str, Type[BaseProvider]] = {
    "groq": GroqProvider,
    "openrouter": OpenRouterProvider,
    "gemini": GeminiProvider,
    "openai": OpenAIProvider,
    "xai": XAIProvider,
}

DEFAULT_PROVIDER = "groq"


def get_provider(name: str | None = None, model: str | None = None, **kwargs) -> BaseProvider:
    """
    Instancie un provider par nom.
    name=None → provider par défaut (settings.AI_DEFAULT_PROVIDER ou groq).
    """
    from django.conf import settings

    key = (name or getattr(settings, "AI_DEFAULT_PROVIDER", DEFAULT_PROVIDER) or DEFAULT_PROVIDER)
    key = key.strip().lower()
    if key not in PROVIDERS:
        raise AIProviderError(
            f"Provider inconnu : « {key} ». Disponibles : {', '.join(PROVIDERS)}",
            code="unknown_provider",
        )
    cls = PROVIDERS[key]
    init_kwargs = dict(kwargs)
    if model:
        init_kwargs["model"] = model
    return cls(**init_kwargs)


def list_providers() -> list[dict]:
    """Métadonnées pour l'UI enseignant (sans exposer les clés)."""
    result = []
    for key, cls in PROVIDERS.items():
        try:
            inst = cls()
            models = inst.list_models()
            configured = bool(inst.api_key and inst.api_key not in ("your_api_key_here", "..."))
        except Exception:
            models = []
            configured = False
        result.append({
            "id": key,
            "label": getattr(cls, "display_name", key),
            "models": models,
            "configured": configured,
        })
    return result


__all__ = [
    "AIProviderError",
    "BaseProvider",
    "PROVIDERS",
    "get_provider",
    "list_providers",
    "GroqProvider",
    "OpenRouterProvider",
    "GeminiProvider",
    "OpenAIProvider",
    "XAIProvider",
]
