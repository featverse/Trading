import numpy as np
import pandas as pd
import pytest

from sentinelle.backtest.engine import CostModel, DataIntegrityError, run_backtest
from sentinelle.backtest.metrics import compute_metrics, drawdown


def test_signal_is_executed_on_next_bar(prices):
    signal = pd.Series(0.0, index=prices.index)
    signal.iloc[10] = 1.0
    bt = run_backtest(prices, signal, CostModel(0, 0))
    assert bt["position"].iloc[10] == 0.0
    assert bt["position"].iloc[11] == 1.0
    assert bt["gross"].iloc[10] == 0.0
    assert bt["gross"].iloc[11] == pytest.approx(bt["returns"].iloc[11])


def test_perfect_foresight_signal_cannot_capture_same_bar_return(prices):
    # Signal « tricheur » : il connaît le rendement de la barre courante.
    cheat = (np.log(prices / prices.shift(1)) > 0).astype(float)
    bt = run_backtest(prices, cheat, CostModel(0, 0))
    gross_if_leaked = (cheat * bt["returns"]).sum()
    assert bt["gross"].sum() < gross_if_leaked * 0.5


def test_costs_applied_on_turnover():
    idx = pd.date_range("2024-01-01", periods=5, freq="D", tz="UTC")
    prices = pd.Series([100.0] * 5, index=idx)
    signal = pd.Series([1.0, 1.0, 0.0, 0.0, 0.0], index=idx)
    bt = run_backtest(prices, signal, CostModel(fee_bps=10, slippage_bps=5))
    assert list(bt["turnover"]) == [0.0, 1.0, 0.0, 1.0, 0.0]
    assert bt["costs"].sum() == pytest.approx(2 * 15 / 1e4)
    assert bt["equity"].iloc[-1] < 1.0  # prix plat : seuls les coûts jouent


def test_zero_signal_keeps_equity_flat(prices):
    bt = run_backtest(prices, pd.Series(0.0, index=prices.index))
    assert (bt["equity"] == 1.0).all()


def test_short_selling_rejected(prices):
    with pytest.raises(ValueError, match="découvert"):
        run_backtest(prices, pd.Series(-1.0, index=prices.index))


def test_leverage_rejected(prices):
    with pytest.raises(ValueError, match="levier"):
        run_backtest(prices, pd.Series(1.0, index=prices.index), max_exposure=2.0)


def test_signal_above_one_is_clipped(prices):
    bt = run_backtest(prices, pd.Series(3.0, index=prices.index))
    assert bt["position"].max() == 1.0


@pytest.mark.parametrize(
    "mutate,msg",
    [
        (lambda p: p.tz_localize(None), "UTC"),
        (lambda p: pd.concat([p, p.iloc[[5]]]).sort_index(), "dupliqués"),
        (lambda p: p.iloc[::-1], "croissants"),
        (lambda p: p.where(p.index != p.index[3]), "NaN"),
    ],
)
def test_bad_data_refused(prices, mutate, msg):
    bad = mutate(prices)
    with pytest.raises(DataIntegrityError, match=msg):
        run_backtest(bad, pd.Series(0.0, index=bad.index))


def test_misaligned_signal_refused(prices):
    with pytest.raises(DataIntegrityError):
        run_backtest(prices, pd.Series(1.0, index=prices.index[:-1]))


def test_metrics_drawdown_known_values():
    idx = pd.date_range("2024-01-01", periods=4, freq="D", tz="UTC")
    eq = pd.Series([1.0, 1.2, 0.9, 1.0], index=idx)
    assert drawdown(eq).min() == pytest.approx(0.9 / 1.2 - 1)


def test_metrics_keys(prices):
    bt = run_backtest(prices, pd.Series(1.0, index=prices.index))
    m = compute_metrics(bt, 365)
    for key in ("sharpe_annualized", "max_drawdown", "skewness", "kurtosis", "total_costs", "n_entries"):
        assert key in m
    assert m["n_entries"] == 1
