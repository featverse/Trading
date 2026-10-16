"""Dimensionnement des positions : Units = Capital × Risk% / |Entrée − Stop|.

Une position n'est JAMAIS dimensionnée à partir d'un objectif de rendement.
"""

from __future__ import annotations

from dataclasses import dataclass

from sentinelle.config import RiskLimits


@dataclass(frozen=True)
class SizingResult:
    allowed: bool
    units: float
    notional: float
    risk_amount: float  # perte estimée si le stop est touché (slippage inclus)
    reason: str


def position_size(
    capital: float,
    entry: float,
    stop: float,
    limits: RiskLimits,
    risk_pct: float | None = None,
) -> SizingResult:
    risk_pct = limits.risk_per_trade if risk_pct is None else risk_pct
    if capital <= 0:
        return SizingResult(False, 0, 0, 0, "Capital nul.")
    if not 0 < risk_pct <= limits.risk_per_trade:
        return SizingResult(False, 0, 0, 0, "Risque demandé au-delà de la limite active.")
    if stop <= 0 or entry <= 0 or stop >= entry:
        return SizingResult(False, 0, 0, 0, "Stop-loss obligatoire et strictement sous l'entrée (spot long).")

    # Risque réel : le stop peut être exécuté plus bas que prévu (slippage, gap).
    effective_stop = stop * (1 - limits.stop_slippage_bps / 1e4)
    risk_per_unit = entry - effective_stop
    units = capital * risk_pct / risk_per_unit
    notional = units * entry

    cap = capital * limits.max_position_pct
    reason = "OK"
    if notional > cap:
        units = cap / entry
        notional = cap
        reason = "Taille plafonnée à l'exposition maximale par position."

    if notional < limits.min_notional_usdt:
        return SizingResult(
            False,
            0,
            notional,
            0,
            f"Position de {notional:.2f} USDT sous le minimum de l'exchange "
            f"({limits.min_notional_usdt} USDT) : capital insuffisant pour trader ce setup.",
        )
    return SizingResult(True, units, notional, units * risk_per_unit, reason)
