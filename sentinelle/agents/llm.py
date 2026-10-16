"""Accès aux modèles Claude pour les agents de recherche.

Les agents ne reçoivent AUCUN outil : ni clé d'exchange, ni exécution de code, ni
réseau. Ils produisent uniquement des objets structurés validés (Pydantic).
"""

from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "claude-opus-5-5"


class LLMRefusal(RuntimeError):
    """Le modèle (et ses fallbacks) a refusé : on n'utilise aucune sortie partielle."""


class LLMOutputError(RuntimeError):
    """Sortie absente, tronquée ou invalide."""


class StructuredLLM(Protocol):
    def structured(self, system: str, user: str, schema: type[T]) -> T: ...


class ClaudeLLM:
    def __init__(self, client=None, model: str = DEFAULT_MODEL, effort: str = "high", max_tokens: int = 16000):
        if client is None:
            import anthropic  # importé ici : les tests n'en ont pas besoin

            client = anthropic.Anthropic()  # ANTHROPIC_API_KEY lue dans l'environnement
        self.client = client
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens

    def structured(self, system: str, user: str, schema: type[T]) -> T:
        response = self.client.beta.messages.parse(
            model=self.model,
            max_tokens=self.max_tokens,
            # Si un filtre de sécurité refuse, l'API relance sur le modèle de repli recommandé.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": self.effort},
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=schema,
        )
        if response.stop_reason == "refusal":
            raise LLMRefusal(f"Refus du modèle : {getattr(response, 'stop_details', None)}")
        if response.stop_reason == "max_tokens":
            raise LLMOutputError("Réponse tronquée (max_tokens).")
        parsed = response.parsed_output
        if parsed is None:
            raise LLMOutputError("Sortie structurée absente.")
        return parsed
