import numpy as np
import pandas as pd
import pytest

from sentinelle.backtest.leakage import check_no_lookahead
from sentinelle.backtest.walkforward import regime_breakdown, regime_labels, walk_forward
from sentinelle.stats.dsr import deflated_sharpe_ratio, expected_max_sharpe
from tests.conftest import make_prices


# --- GATE 1 : détection de fuite ---------------------------------------------
def honest_sma(p: pd.Series) -> pd.Series:
    return (p > p.rolling(20).mean()).astype(float)


def centered_sma(p: pd.Series) -> pd.Series:
    return (p > p.rolling(21, center=True).mean()).astype(float)


def peeks_tomorrow(p: pd.Series) -> pd.Series:
    return (p.shift(-1) > p).astype(float)


def zscore_full_sample(p: pd.Series) -> pd.Series:
    return ((p - p.mean()) / p.std() > 0).astype(float)


def test_honest_indicator_passes(prices):
    assert check_no_lookahead(honest_sma, prices).passed


@pytest.mark.parametrize("fn", [centered_sma, peeks_tomorrow, zscore_full_sample])
def test_leaky_indicators_detected(prices, fn):
    report = check_no_lookahead(fn, prices)
    assert not report.passed
    assert report.failures


# --- GATE 2 : Deflated Sharpe -------------------------------------------------
def test_expected_max_sharpe_grows_with_trials():
    assert expected_max_sharpe(1, 0.01) == 0.0
    assert expected_max_sharpe(100, 0.01) > expected_max_sharpe(10, 0.01) > 0


def test_noise_best_of_many_trials_is_rejected():
    rng = np.random.default_rng(1)
    trials = [rng.normal(0, 0.02, 500) for _ in range(200)]
    sharpes = [t.mean() / t.std(ddof=1) for t in trials]
    best = trials[int(np.argmax(sharpes))]
    res = deflated_sharpe_ratio(max(sharpes), sharpes, len(best), 0.0, 3.0)
    assert not res.passed
    assert "REJECT" in res.explain()


def test_genuine_edge_with_one_trial_passes():
    res = deflated_sharpe_ratio(0.15, [0.15], n_obs=1000, skewness=0.0, kurtosis=3.0)
    assert res.passed


# --- GATE 3 : walk-forward -----------------------------------------------------
def sma_factory(params):
    w = params["window"]
    return lambda p: (p > p.rolling(w).mean()).astype(float)


def test_walk_forward_never_sees_test_data_when_selecting():
    prices = make_prices(800, seed=3)
    seen_ends: list[pd.Timestamp] = []

    def spy_factory(params):
        def fn(p):
            seen_ends.append(p.index[-1])
            return (p > p.rolling(params["window"]).mean()).astype(float)
        return fn

    res = walk_forward(prices, spy_factory, [{"window": 10}, {"window": 30}], 360, 60, 365, warmup_bars=30)
    grid_len = 2
    per_fold = grid_len + 1  # sélection sur le train puis 1 évaluation sur le test
    for i, row in res.folds.iterrows():
        train_calls = seen_ends[i * per_fold : i * per_fold + grid_len]
        assert all(end < row["test_start"] for end in train_calls)
    assert res.n_trials == grid_len * len(res.folds)


def test_random_walk_strategy_not_validated():
    prices = make_prices(1500, seed=7)
    grid = [{"window": w} for w in (10, 20, 50, 100)]
    res = walk_forward(prices, sma_factory, grid, 360, 90, 365, warmup_bars=100)
    assert len(res.folds) >= 5
    # Sur une marche aléatoire, on ne doit pas « découvrir » d'edge robuste.
    assert not (res.passed and res.positive_fold_ratio == 1.0)


def test_regimes_use_past_only(prices):
    assert check_no_lookahead(lambda p: regime_labels(p).map({"bull": 1.0, "bear": -1.0, "chop": 0.0, "unknown": np.nan}), prices).passed
    labels = regime_labels(prices)
    table = regime_breakdown(pd.Series(0.001, index=prices.index), labels)
    assert set(table.index) <= {"bull", "bear", "chop", "unknown"}
