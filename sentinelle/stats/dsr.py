"""GATE 2 — Deflated Sharpe Ratio (Bailey & López de Prado).

Travaille avec des Sharpe PAR PÉRIODE (non annualisés), cohérents avec T.
Chaque combinaison de paramètres, fenêtre, filtre ou timeframe essayé compte comme
un essai : N doit être le nombre RÉEL d'essais, pas 1.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
from scipy.stats import norm

EULER_GAMMA = 0.5772156649015329
DSR_THRESHOLD = 0.95


@dataclass(frozen=True)
class DSRResult:
    n_trials: int
    n_obs: int
    sharpe: float
    expected_max_sharpe: float
    dsr: float
    passed: bool

    def explain(self) -> str:
        verdict = "PASS" if self.passed else "REJECT"
        return (
            f"{verdict} — N={self.n_trials} essais, T={self.n_obs} obs, Sharpe/période="
            f"{self.sharpe:.4f}, Sharpe max attendu par hasard={self.expected_max_sharpe:.4f}, "
            f"DSR={self.dsr:.3f} (seuil {DSR_THRESHOLD})."
        )


def expected_max_sharpe(n_trials: int, var_trial_sharpes: float) -> float:
    """Sharpe maximal attendu parmi N essais de bruit pur."""
    if n_trials < 1:
        raise ValueError("n_trials doit être >= 1.")
    if n_trials == 1:
        return 0.0
    z = (1 - EULER_GAMMA) * norm.ppf(1 - 1 / n_trials) + EULER_GAMMA * norm.ppf(
        1 - 1 / (n_trials * np.e)
    )
    return float(np.sqrt(max(var_trial_sharpes, 0.0)) * z)


def deflated_sharpe_ratio(
    sharpe: float,
    trial_sharpes: Sequence[float],
    n_obs: int,
    skewness: float,
    kurtosis: float,
    threshold: float = DSR_THRESHOLD,
) -> DSRResult:
    """`kurtosis` est la kurtosis brute (3 pour une loi normale)."""
    n_trials = len(trial_sharpes)
    if n_trials < 1:
        raise ValueError("Fournir les Sharpe de TOUS les essais (au moins 1).")
    if n_obs < 2:
        raise ValueError("n_obs doit être >= 2.")
    var = float(np.var(trial_sharpes, ddof=1)) if n_trials > 1 else 0.0
    sr0 = expected_max_sharpe(n_trials, var)
    denom = 1 - skewness * sharpe + ((kurtosis - 1) / 4) * sharpe**2
    if denom <= 0:
        # Distribution pathologique : on refuse de conclure en faveur de la stratégie.
        return DSRResult(n_trials, n_obs, sharpe, sr0, 0.0, False)
    z = (sharpe - sr0) * np.sqrt(n_obs - 1) / np.sqrt(denom)
    dsr = float(norm.cdf(z))
    return DSRResult(n_trials, n_obs, sharpe, sr0, dsr, dsr > threshold)
