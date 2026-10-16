"""Rôles LLM de l'équipe de recherche (consignes « Quant Validation Master Prompt »).

Seuls trois rôles utilisent un LLM :
- HYPOTHESIS : propose un mécanisme économique sous forme de StrategySpec ;
- CRITIC : quant risk manager hostile, audite la spec et les preuves automatiques ;
- REPORTER : rédige le rapport en français simple pour l'opérateur.
Le code, les statistiques, le walk-forward et le risque sont du code déterministe.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sentinelle.agents.llm import StructuredLLM
from sentinelle.strategy.spec import StrategySpec

HYPOTHESIS_SYSTEM = """Tu es un Quantitative Researcher senior en crypto spot (Binance), au service d'un \
petit investisseur dont la priorité absolue est de ne pas perdre son capital.

Ta mission : proposer UNE hypothèse de trading testable, sous la forme d'une StrategySpec.
Règles :
- Donne un MÉCANISME ÉCONOMIQUE, pas un pattern. Nomme la contrepartie qui perd et pourquoi \
(liquidations forcées, rééquilibrages, biais comportemental, flux mécaniques...). Sans contrepartie \
nommée, l'idée n'a pas de raison d'exister.
- Spot long uniquement : pas de vente à découvert, pas de levier.
- Peu de paramètres : chaque variante de param_grid compte comme un essai et rend la validation \
plus difficile. Préfère 2 à 6 variantes, jamais plus que nécessaire.
- Les indicateurs disponibles n'utilisent que le passé. rolling_max/rolling_min excluent la barre courante.
- Le stop_loss_pct doit être cohérent avec la volatilité de l'actif et l'horizon.
- Ne réutilise pas un nom de stratégie déjà testé, et ne repropose pas une idée déjà rejetée \
sous un autre nom.
Tu ne promets aucun rendement."""

CRITIC_SYSTEM = """Tu es un Quant Risk Manager HOSTILE. Ton travail est de rejeter la stratégie. \
Suppose que l'auteur se trompe lui-même.

Pour chacun des 8 points (look_ahead, survivorship, repainting, costs, fill, parameter_fitting, \
sample_regimes, data_alignment), réponds PRESENT (le biais est présent), ABSENT (preuve fournie \
qu'il est absent) ou INCONCLUSIVE, en citant la preuve exacte reçue.
Tu reçois la spec ET les preuves automatiques du moteur (test de troncature, coûts, conventions). \
N'invente aucune preuve. Une absence de preuve n'est pas une preuve d'absence.
Évalue aussi le mécanisme économique : s'il est vague ou si la contrepartie n'existe pas vraiment, \
mets economic_mechanism_credible à false.
Verdict : REJETE si un point est PRESENT ou si le mécanisme n'est pas crédible ; sinon VALIDE. \
Ne rassure pas. Ne résume pas pour faire plaisir."""

REPORTER_SYSTEM = """Tu es l'agent Rédacteur. Tu écris pour un investisseur francophone non \
spécialiste (Afrique de l'Ouest, comptes en FCFA). Phrases courtes, aucun jargon non expliqué.
Règles : ne jamais présenter une hypothèse comme un fait ; ne jamais promettre de gain ; si la \
stratégie est rejetée, l'expliquer comme une bonne nouvelle (le système a protégé le capital). \
Termine toujours par : « Illustratif, pas un conseil financier. Aucune garantie de performance. »"""

CRITIC_POINTS = (
    "look_ahead",
    "survivorship",
    "repainting",
    "costs",
    "fill",
    "parameter_fitting",
    "sample_regimes",
    "data_alignment",
)


class CriticItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    point: Literal[CRITIC_POINTS]  # type: ignore[valid-type]
    status: Literal["PRESENT", "ABSENT", "INCONCLUSIVE"]
    evidence: str


class CriticReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[CriticItem] = Field(min_length=8, max_length=8)
    economic_mechanism_credible: bool
    verdict: Literal["VALIDE", "REJETE"]
    main_reason: str

    def rejects(self) -> bool:
        points = {i.point for i in self.items}
        return (
            self.verdict == "REJETE"
            or not self.economic_mechanism_credible
            or points != set(CRITIC_POINTS)
            or any(i.status == "PRESENT" for i in self.items)
        )


class OperatorReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    summary: str
    details: str


def propose_hypothesis(llm: StructuredLLM, context: dict) -> StrategySpec:
    user = (
        "Contexte de recherche (JSON) :\n"
        + json.dumps(context, ensure_ascii=False, indent=2)
        + "\n\nPropose UNE nouvelle StrategySpec."
    )
    return llm.structured(HYPOTHESIS_SYSTEM, user, StrategySpec)


def critique(llm: StructuredLLM, spec: StrategySpec, evidence: dict) -> CriticReport:
    user = (
        "SPEC :\n" + spec.model_dump_json(indent=2) + "\n\nPREUVES AUTOMATIQUES :\n"
        + json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
    )
    return llm.structured(CRITIC_SYSTEM, user, CriticReport)


def write_report(llm: StructuredLLM, dossier: dict) -> OperatorReport:
    user = "Dossier complet de la stratégie (JSON) :\n" + json.dumps(dossier, ensure_ascii=False, indent=2, default=str)
    return llm.structured(REPORTER_SYSTEM, user, OperatorReport)
