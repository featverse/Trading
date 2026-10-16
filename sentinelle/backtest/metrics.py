"""Métriques qui ne mentent pas : le Sharpe est un résultat à auditer, pas une preuve."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats as sps

# Crypto : marché 24h/24, 7j/7.
PERIODS_PER_YEAR = {"1d": 365, "4h": 365 * 6, "1h": 365 * 24, "15m": 365 * 96}


def drawdown(equity: pd.Series) -> pd.Series:
    return equity / equity.cummax() - 1.0


def max_drawdown_duration(equity: pd.Series) -> int:
    """Plus longue période (en barres) passée sous le dernier plus haut."""
    underwater = (equity < equity.cummax()).to_numpy()
    longest = current = 0
    for flag in underwater:
        current = current + 1 if flag else 0
        longest = max(longest, current)
    return longest


def sharpe_per_period(net: pd.Series) -> float:
    std = net.std(ddof=1)
    if not np.isfinite(std) or std == 0:
        return 0.0
    return float(net.mean() / std)


def compute_metrics(bt: pd.DataFrame, periods_per_year: int) -> dict[str, float]:
    net = bt["net"]
    equity = bt["equity"]
    n = len(net)
    sr = sharpe_per_period(net)
    ann_return = float(np.exp(net.mean() * periods_per_year) - 1.0)
    mdd = float(drawdown(equity).min())
    entries = ((bt["position"] > 0) & (bt["position"].shift(1).fillna(0) == 0)).sum()
    return {
        "n_obs": float(n),
        "sharpe_per_period": sr,
        "sharpe_annualized": sr * float(np.sqrt(periods_per_year)),
        "annual_return": ann_return,
        "annual_vol": float(net.std(ddof=1) * np.sqrt(periods_per_year)),
        "total_return": float(equity.iloc[-1] - 1.0),
        "max_drawdown": mdd,
        "max_drawdown_duration_bars": float(max_drawdown_duration(equity)),
        "calmar": float(ann_return / abs(mdd)) if mdd < 0 else float("inf"),
        "skewness": float(sps.skew(net, bias=False)) if n > 2 else 0.0,
        # Kurtosis « brute » (= 3 pour une loi normale), comme l'attend la formule du DSR.
        "kurtosis": float(sps.kurtosis(net, fisher=False, bias=False)) if n > 3 else 3.0,
        "turnover": float(bt["turnover"].sum()),
        "total_costs": float(bt["costs"].sum()),
        "avg_exposure": float(bt["position"].mean()),
        "max_exposure": float(bt["position"].max()),
        "n_entries": float(entries),
    }
