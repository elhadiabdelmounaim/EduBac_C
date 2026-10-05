"""
Interface commune pour tous les fournisseurs IA.
Le Quiz Generator ne dépend jamais d'un provider concret.
"""
from __future__ import annotations

import abc
import logging
from typing import Any

logger = logging.getLogger(__name__)


class AIProviderError(Exception):
    """Erreur métier provider (clé manquante, rate limit, timeout, etc.)."""

    def __init__(self, message: str, code: str = "provider_error"):
        super().__init__(message)
        self.code = code


class BaseProvider(abc.ABC):
    """Contrat minimal : chat completion texte → str."""

    name: str = "base"
    display_name: str = "Base"

    def __init__(self, api_key: str = "", model: str = "", **kwargs):
        self.api_key = (api_key or "").strip()
        self.model = (model or "").strip()
        self.timeout = int(kwargs.get("timeout", 90))

    def ensure_configured(self):
        if not self.api_key or self.api_key in ("your_api_key_here", "..."):
            raise AIProviderError(
                f"Clé API manquante pour {self.display_name}. "
                f"Configurez-la dans le fichier .env.",
                code="missing_api_key",
            )
        if not self.model:
            raise AIProviderError(
                f"Modèle non configuré pour {self.display_name}.",
                code="missing_model",
            )

    @abc.abstractmethod
    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> str:
        """
        Envoie une conversation chat et retourne le contenu texte de la réponse.
        Lève AIProviderError en cas d'échec (jamais d'exception non gérée vers Django).
        """
        raise NotImplementedError

    def list_models(self) -> list[dict[str, str]]:
        """Liste indicative de modèles gratuits / recommandés (pour l'UI)."""
        return []
