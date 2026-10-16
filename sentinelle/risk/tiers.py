"""Paliers de capital (FCFA) et mise à l'abri des gains.

L'argent mis à l'abri ne retourne jamais au trading.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tier:
    name: str
    min_fcfa: float
    live_trading: bool
    risk_per_trade: float
    max_strategies: int
    description: str


TIERS: tuple[Tier, ...] = (
    Tier("P0", 0, False, 0.0, 0, "DCA BTC/ETH + paper trading de l'IA (capital trop petit pour trader)."),
    Tier("P1", 50_000, True, 0.005, 1, "Réel, risque 0,5 %, une seule stratégie validée."),
    Tier("P2", 100_000, True, 0.01, 3, "Risque 1 %, jusqu'à 3 stratégies non corrélées."),
    Tier("P3", 1_000_000, True, 0.01, 5, "Diversification, retraits réguliers possibles."),
)


def tier_for(equity_fcfa: float) -> Tier:
    current = TIERS[0]
    for tier in TIERS:
        if equity_fcfa >= tier.min_fcfa:
            current = tier
    return current


def milestone_secure_pct(milestone_fcfa: float) -> float:
    return 0.25 if milestone_fcfa >= 1_000_000 else 0.20


@dataclass
class MilestoneTracker:
    """Paliers tous les 100 000 FCFA. Les gains comptent hors apports."""

    initial_capital: float
    step_fcfa: float = 100_000
    last_milestone: float = 0.0
    equity_at_last_milestone: float = 0.0
    deposits_since: float = 0.0
    total_secured: float = 0.0

    def __post_init__(self) -> None:
        if self.initial_capital < 0:
            raise ValueError("Capital initial invalide.")
        self.equity_at_last_milestone = self.initial_capital
        self.last_milestone = (self.initial_capital // self.step_fcfa) * self.step_fcfa

    def deposit(self, amount_fcfa: float) -> None:
        if amount_fcfa <= 0:
            raise ValueError("Apport invalide.")
        self.deposits_since += amount_fcfa

    def check(self, equity_fcfa: float) -> float:
        """Renvoie le montant à mettre à l'abri (0 si aucun nouveau palier)."""
        next_milestone = self.last_milestone + self.step_fcfa
        if equity_fcfa < next_milestone:
            return 0.0
        reached = (equity_fcfa // self.step_fcfa) * self.step_fcfa
        gains = equity_fcfa - self.equity_at_last_milestone - self.deposits_since
        to_secure = max(0.0, gains) * milestone_secure_pct(reached)
        self.last_milestone = reached
        self.equity_at_last_milestone = equity_fcfa - to_secure
        self.deposits_since = 0.0
        self.total_secured += to_secure
        return to_secure


def project_months_to_target(
    start_fcfa: float, monthly_deposit_fcfa: float, monthly_return: float, target_fcfa: float, max_months: int = 1200
) -> int | None:
    """Projection ILLUSTRATIVE à rendement constant (la réalité ne l'est jamais)."""
    capital, month = start_fcfa, 0
    while capital < target_fcfa:
        if month >= max_months:
            return None
        capital = capital * (1 + monthly_return) + monthly_deposit_fcfa
        month += 1
    return month
