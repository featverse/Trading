from datetime import datetime, timedelta, timezone

import pytest

from sentinelle.config import RiskConfigError, RiskLimits
from sentinelle.risk.guard import RESET_CONFIRMATION, OpenPosition, OrderRequest, RiskGuard, Status
from sentinelle.risk.sizing import position_size
from sentinelle.risk.tiers import MilestoneTracker, project_months_to_target, tier_for

T0 = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)
LIM = RiskLimits(risk_per_trade=0.01, min_notional_usdt=5.0)


# --- Plafonds absolus ------------------------------------------------------------
@pytest.mark.parametrize(
    "kwargs",
    [
        {"risk_per_trade": 0.02},
        {"max_position_pct": 0.5},
        {"max_total_exposure": 1.0},
        {"max_drawdown": 0.3},
        {"daily_loss_limit": 0.1},
        {"max_positions": 10},
    ],
)
def test_limits_cannot_exceed_hard_ceilings(kwargs):
    with pytest.raises(RiskConfigError):
        RiskLimits(**kwargs)


# --- Dimensionnement ---------------------------------------------------------------
def test_sizing_formula():
    lim = RiskLimits(risk_per_trade=0.01, stop_slippage_bps=0)
    r = position_size(capital=1000, entry=100, stop=95, limits=lim)
    # 1000 × 1 % / 5 = 2 unités = 200 USDT, ce qui atteint juste le plafond de 20 %.
    assert r.allowed and r.units == pytest.approx(2.0) and r.risk_amount == pytest.approx(10.0)


def test_sizing_capped_by_max_position():
    lim = RiskLimits(risk_per_trade=0.01, stop_slippage_bps=0)
    r = position_size(capital=1000, entry=100, stop=99.5, limits=lim)
    assert r.notional == pytest.approx(200.0)
    assert r.risk_amount < 10.0


def test_sizing_refuses_without_valid_stop():
    assert not position_size(1000, 100, 100, LIM).allowed
    assert not position_size(1000, 100, 105, LIM).allowed


def test_small_capital_blocked_by_exchange_minimum():
    # 20 000 FCFA ≈ 33 USDT : 20 % = 6,6 USDT ; avec un stop large, la taille tombe sous 5 USDT.
    r = position_size(capital=33, entry=100, stop=80, limits=LIM)
    assert not r.allowed and "minimum" in r.reason


# --- Gardien -----------------------------------------------------------------------
def make_guard(equity=1000.0):
    return RiskGuard(LIM, equity, T0)


def good_order(**over):
    base = dict(symbol="BTC/USDT", side="buy", entry_price=100.0, stop_price=97.0, notional=150.0)
    base.update(over)
    return OrderRequest(**base)


def test_valid_order_approved():
    g = make_guard()
    d = g.check_new_order(good_order(), [], 1000, T0, last_data_time=T0)
    assert d.approved, d.reasons


@pytest.mark.parametrize(
    "over,needle",
    [
        ({"market_type": "futures"}, "spot"),
        ({"leverage": 5.0}, "Levier"),
        ({"stop_price": None}, "Stop-loss"),
        ({"symbol": "PEPE/USDT"}, "hors de la liste"),
        ({"notional": 500.0}, "Position >"),
        ({"side": "sell"}, "entrées longues"),
        ({"notional": 2.0}, "minimum"),
    ],
)
def test_forbidden_orders_rejected(over, needle):
    d = make_guard().check_new_order(good_order(**over), [], 1000, T0, last_data_time=T0)
    assert not d.approved
    assert any(needle in r for r in d.reasons), d.reasons


def test_stale_data_blocks_entries():
    d = make_guard().check_new_order(good_order(), [], 1000, T0, last_data_time=T0 - timedelta(minutes=10))
    assert not d.approved


def test_exposure_and_position_count_limits():
    g = make_guard()
    opens = [OpenPosition("ETH/USDT", 250), OpenPosition("SOL/USDT", 250)]
    d = g.check_new_order(good_order(notional=150), opens, 1000, T0, last_data_time=T0)
    assert not d.approved and any("Exposition totale" in r for r in d.reasons)
    d = g.check_new_order(good_order(), [OpenPosition("BTC/USDT", 100)], 1000, T0, last_data_time=T0)
    assert any("martingale" in r for r in d.reasons)


def test_order_risk_above_allowed_rejected():
    # 200 USDT avec un stop à -10 % = 20 USDT de risque > 1 % de 1000.
    d = make_guard().check_new_order(good_order(notional=200, stop_price=90), [], 1000, T0, last_data_time=T0)
    assert not d.approved and any("Risque" in r for r in d.reasons)


def test_daily_loss_pauses_until_next_utc_day():
    g = make_guard()
    assert g.update_equity(965, T0) == Status.PAUSED_DAILY
    assert not g.check_new_order(good_order(), [], 965, T0, last_data_time=T0).approved
    tomorrow = T0 + timedelta(days=1)
    assert g.check_new_order(good_order(notional=100), [], 965, tomorrow, last_data_time=tomorrow).approved


def test_drawdown_halts_and_requires_manual_reset():
    g = make_guard()
    g.update_equity(1100, T0)
    days = [T0 + timedelta(days=i) for i in range(1, 6)]
    for day, eq in zip(days, (1080, 1060, 1040, 1010, 985)):
        g.update_equity(eq, day)
    assert g.state.status == Status.HALTED
    # Plusieurs jours plus tard : toujours arrêté, pas de reprise automatique.
    later = T0 + timedelta(days=30)
    g.update_equity(990, later)
    assert g.state.status == Status.HALTED
    assert not g.manual_reset("ok", later)
    assert g.manual_reset(RESET_CONFIRMATION, later)
    assert g.state.status == Status.ACTIVE


def test_loss_streak_halves_risk_then_pauses():
    g = make_guard()
    for i in range(4):
        g.record_trade_result(-5, T0 + timedelta(hours=i))
    assert g.current_risk_pct() == pytest.approx(0.005)
    for i in range(4, 6):
        g.record_trade_result(-5, T0 + timedelta(hours=i))
    assert g.state.status == Status.PAUSED_LOSS_STREAK
    after = T0 + timedelta(hours=60)
    assert g.check_new_order(good_order(notional=100), [], 1000, after, last_data_time=after).approved


def test_live_performance_kill_conditions():
    g = make_guard()
    assert g.check_live_performance(0.4, 1.0, -0.02, -0.08, T0) == Status.HALTED
    g2 = make_guard()
    assert g2.check_live_performance(1.0, 1.0, -0.13, -0.08, T0) == Status.HALTED
    g3 = make_guard()
    assert g3.check_live_performance(0.9, 1.0, -0.05, -0.08, T0) == Status.ACTIVE


def test_emergency_stop_and_persistence():
    g = make_guard()
    g.emergency_stop(T0)
    restored = RiskGuard.from_json(LIM, g.to_json())
    assert restored.state.status == Status.HALTED
    assert restored.state.events[-1]["kind"] == "HALT"


def test_naive_datetime_refused():
    with pytest.raises(ValueError):
        RiskGuard(LIM, 1000, datetime(2026, 1, 1))


# --- Paliers ---------------------------------------------------------------------------
def test_tiers():
    assert not tier_for(20_000).live_trading
    assert tier_for(60_000).name == "P1"
    assert tier_for(150_000).risk_per_trade == 0.01
    assert tier_for(2_000_000).name == "P3"


def test_milestone_secures_only_gains_not_deposits():
    t = MilestoneTracker(initial_capital=20_000)
    for _ in range(4):
        t.deposit(20_000)
    # 100 000 = 20 000 initial + 80 000 d'apports : aucun gain, rien à mettre à l'abri.
    assert t.check(100_000) == 0.0
    assert t.last_milestone == 100_000
    t.deposit(20_000)
    # 210 000 : +110 000 depuis le palier précédent, dont 20 000 d'apport → 90 000 de gains.
    assert t.check(210_000) == pytest.approx(0.20 * 90_000)
    assert t.check(215_000) == 0.0


def test_projection_for_user_plan():
    months = project_months_to_target(20_000, 20_000, 0.02, 1_000_000)
    assert months is not None and 30 < months < 50
