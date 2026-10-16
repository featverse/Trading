"""Détection automatique de look-ahead / repainting par test de troncature.

Principe : un signal honnête à la date t ne dépend QUE des données <= t. Donc calculer
la stratégie sur les données tronquées à t doit donner exactement les mêmes valeurs
jusqu'à t que sur l'historique complet. Une moyenne centrée, un shift(-1), un zigzag
ou une normalisation sur tout le dataset échouent à ce test.

Ce test complète l'audit Critic (8 points) ; il ne le remplace pas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

SignalFn = Callable[[pd.Series], pd.Series]


@dataclass
class LeakageReport:
    passed: bool
    checked_cutoffs: list[pd.Timestamp] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


def check_no_lookahead(
    signal_fn: SignalFn,
    prices: pd.Series,
    n_cutoffs: int = 8,
    min_bars: int = 50,
    atol: float = 1e-12,
) -> LeakageReport:
    full = signal_fn(prices)
    if not full.index.equals(prices.index):
        return LeakageReport(False, failures=["Le signal ne conserve pas l'index des prix."])

    if len(prices) <= min_bars + 1:
        return LeakageReport(False, failures=["Historique trop court pour le test de troncature."])

    cut_positions = np.unique(np.linspace(min_bars, len(prices) - 2, n_cutoffs).astype(int))
    report = LeakageReport(passed=True)
    for k in cut_positions:
        truncated = prices.iloc[: k + 1]
        partial = signal_fn(truncated)
        reference = full.iloc[: k + 1]
        a = partial.to_numpy(dtype=float)
        b = reference.to_numpy(dtype=float)
        same = np.isclose(a, b, atol=atol, equal_nan=True)
        report.checked_cutoffs.append(prices.index[k])
        if not same.all():
            first_bad = reference.index[int(np.argmin(same))]
            report.passed = False
            report.failures.append(
                f"Coupure {prices.index[k]} : le signal du {first_bad} change quand on "
                "ajoute des données futures (look-ahead / repainting)."
            )
    return report
