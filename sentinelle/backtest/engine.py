"""Moteur de backtest « inviolable » — infrastructure critique.

Conventions (explicites, non négociables) :
- index : DatetimeIndex en UTC, strictement croissant, sans doublon ;
- prix : prix de CLÔTURE de chaque barre ;
- un signal calculé à la clôture de t ne devient une position qu'en t+1 (shift(1)) ;
- spot uniquement : position dans [0, max_exposure] avec max_exposure <= 1 (pas de
  vente à découvert, pas de levier) ;
- frais ET slippage appliqués sur le turnover (variation d'exposition).

Ne pas modifier ce fichier pour « améliorer » un résultat : toute modification passe
par une revue et les tests de tests/test_engine.py.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from sentinelle.config import MAX_LEVERAGE


@dataclass(frozen=True)
class CostModel:
    fee_bps: float = 10.0  # Binance spot taker ≈ 0,10 % (à vérifier selon ton niveau VIP/BNB)
    slippage_bps: float = 5.0

    def __post_init__(self) -> None:
        if self.fee_bps < 0 or self.slippage_bps < 0:
            raise ValueError("Les coûts ne peuvent pas être négatifs.")

    @property
    def total_bps(self) -> float:
        return self.fee_bps + self.slippage_bps


class DataIntegrityError(ValueError):
    """Données de marché invalides : le backtest refuse de tourner."""


def validate_prices(prices: pd.Series) -> None:
    if not isinstance(prices, pd.Series):
        raise DataIntegrityError("prices doit être une pd.Series.")
    idx = prices.index
    if not isinstance(idx, pd.DatetimeIndex):
        raise DataIntegrityError("L'index doit être un DatetimeIndex.")
    if idx.tz is None or str(idx.tz) != "UTC":
        raise DataIntegrityError("L'index doit être en UTC explicite.")
    if idx.has_duplicates:
        raise DataIntegrityError("Timestamps dupliqués dans les prix.")
    if not idx.is_monotonic_increasing:
        raise DataIntegrityError("Timestamps non croissants.")
    if prices.isna().any():
        raise DataIntegrityError("Prix manquants (NaN) : à traiter explicitement avant le backtest.")
    if (prices <= 0).any():
        raise DataIntegrityError("Prix nuls ou négatifs.")
    if len(prices) < 2:
        raise DataIntegrityError("Au moins 2 barres sont nécessaires.")


def run_backtest(
    prices: pd.Series,
    signal: pd.Series,
    costs: CostModel = CostModel(),
    max_exposure: float = 1.0,
) -> pd.DataFrame:
    """Backtest vectorisé, spot long-only.

    Retourne un DataFrame : price, signal, position, returns, gross, turnover, costs,
    net, equity. `signal` est l'exposition DÉSIRÉE décidée à la clôture de la barre.
    """
    validate_prices(prices)
    if not 0 < max_exposure <= MAX_LEVERAGE:
        raise ValueError(f"max_exposure doit être dans ]0, {MAX_LEVERAGE}] : levier interdit.")
    if not isinstance(signal, pd.Series) or not signal.index.equals(prices.index):
        raise DataIntegrityError("Le signal doit avoir exactement le même index que les prix.")

    sig = signal.astype(float).fillna(0.0)
    if (sig < 0).any():
        raise ValueError("Signal négatif : la vente à découvert est interdite (spot uniquement).")

    # LA LIGNE LA PLUS IMPORTANTE : on agit sur la barre SUIVANTE.
    position = sig.shift(1).fillna(0.0).clip(0.0, max_exposure)

    returns = np.log(prices / prices.shift(1)).fillna(0.0)
    gross = position * returns
    turnover = position.diff().abs().fillna(position.abs())
    cost = turnover * costs.total_bps / 1e4
    net = gross - cost
    equity = np.exp(net.cumsum())

    return pd.DataFrame(
        {
            "price": prices,
            "signal": sig,
            "position": position,
            "returns": returns,
            "gross": gross,
            "turnover": turnover,
            "costs": cost,
            "net": net,
            "equity": equity,
        }
    )
