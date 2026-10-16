"""GATE 3 — Validation walk-forward hors échantillon + analyse par régime.

Règles :
- les paramètres sont choisis sur TRAIN uniquement ;
- le TEST n'influence jamais la sélection ;
- chaque fold est conservé, y compris les négatifs ;
- jugement sur la proportion de folds positifs et le PIRE fold, jamais sur la moyenne.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

import numpy as np
import pandas as pd

from sentinelle.backtest.engine import CostModel, run_backtest
from sentinelle.backtest.metrics import compute_metrics, drawdown, sharpe_per_period

Params = Mapping[str, Any]
StrategyFactory = Callable[[Params], Callable[[pd.Series], pd.Series]]


@dataclass
class WalkForwardResult:
    folds: pd.DataFrame
    n_trials: int
    positive_fold_ratio: float
    worst_fold_return: float
    concentration: float  # part du gain total apportée par le meilleur fold
    passed: bool
    reasons: list[str]
    oos_net: pd.Series  # rendements nets hors échantillon concaténés


def walk_forward(
    prices: pd.Series,
    factory: StrategyFactory,
    param_grid: Iterable[Params],
    train_bars: int,
    test_bars: int,
    periods_per_year: int,
    warmup_bars: int = 0,
    costs: CostModel = CostModel(),
    min_positive_ratio: float = 0.6,
    max_worst_fold_loss: float = 0.10,
    max_concentration: float = 0.5,
) -> WalkForwardResult:
    grid = list(param_grid)
    if not grid:
        raise ValueError("param_grid vide.")
    if warmup_bars > train_bars:
        raise ValueError("La période de chauffe doit être prise dans le train.")

    rows: list[dict[str, Any]] = []
    oos_parts: list[pd.Series] = []
    start = 0
    while start + train_bars + test_bars <= len(prices):
        train = prices.iloc[start : start + train_bars]
        best_params, best_sr = None, -np.inf
        for params in grid:
            bt = run_backtest(train, factory(params)(train), costs)
            sr = sharpe_per_period(bt["net"])
            if sr > best_sr:
                best_params, best_sr = params, sr

        # Le test reçoit une chauffe issue du passé (fin du train) : aucune donnée future.
        t0 = start + train_bars
        window = prices.iloc[t0 - warmup_bars : t0 + test_bars]
        bt_window = run_backtest(window, factory(best_params)(window), costs)
        bt_test = bt_window.iloc[warmup_bars:].copy()
        bt_test["equity"] = np.exp(bt_test["net"].cumsum())
        m = compute_metrics(bt_test, periods_per_year)
        rows.append(
            {
                "test_start": bt_test.index[0],
                "test_end": bt_test.index[-1],
                "params": dict(best_params),
                "train_sharpe": best_sr,
                "test_sharpe_ann": m["sharpe_annualized"],
                "test_return": m["total_return"],
                "test_max_drawdown": m["max_drawdown"],
            }
        )
        oos_parts.append(bt_test["net"])
        start += test_bars

    if not rows:
        raise ValueError("Historique trop court pour un seul fold.")

    folds = pd.DataFrame(rows)
    returns = folds["test_return"]
    positive_ratio = float((returns > 0).mean())
    worst = float(returns.min())
    gains = returns[returns > 0]
    concentration = float(gains.max() / gains.sum()) if len(gains) else 1.0

    reasons: list[str] = []
    if positive_ratio < min_positive_ratio:
        reasons.append(f"Folds positifs {positive_ratio:.0%} < {min_positive_ratio:.0%}.")
    if worst < -max_worst_fold_loss:
        reasons.append(f"Pire fold {worst:.1%} au-delà de -{max_worst_fold_loss:.0%}.")
    if len(gains) > 1 and concentration > max_concentration:
        reasons.append(f"Gain concentré : un seul fold apporte {concentration:.0%} du total.")
    if len(gains) <= 1:
        reasons.append("Au plus un fold gagnant : edge non démontré.")

    return WalkForwardResult(
        folds=folds,
        n_trials=len(grid) * len(rows),
        positive_fold_ratio=positive_ratio,
        worst_fold_return=worst,
        concentration=concentration,
        passed=not reasons,
        reasons=reasons,
        oos_net=pd.concat(oos_parts),
    )


def regime_labels(prices: pd.Series, ma_bars: int = 200, slope_bars: int = 20) -> pd.Series:
    """Bull / bear / chop à partir de la MA200 — données passées uniquement."""
    ma = prices.rolling(ma_bars, min_periods=ma_bars).mean()
    slope = ma - ma.shift(slope_bars)
    labels = pd.Series("chop", index=prices.index, dtype=object)
    labels[(prices > ma) & (slope > 0)] = "bull"
    labels[(prices < ma) & (slope < 0)] = "bear"
    labels[ma.isna() | slope.isna()] = "unknown"
    return labels


def regime_breakdown(net: pd.Series, labels: pd.Series) -> pd.DataFrame:
    """Rendement et Sharpe par régime. Si l'edge n'existe que dans un régime, le dire."""
    aligned = labels.reindex(net.index)
    out = []
    for regime, part in net.groupby(aligned):
        eq = np.exp(part.cumsum())
        out.append(
            {
                "regime": regime,
                "n_obs": len(part),
                "total_return": float(eq.iloc[-1] - 1),
                "sharpe_per_period": sharpe_per_period(part),
                "max_drawdown": float(drawdown(eq).min()),
            }
        )
    return pd.DataFrame(out).set_index("regime")
