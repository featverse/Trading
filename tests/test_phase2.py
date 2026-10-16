import importlib.util
import json
import sys
import types
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from sentinelle.agents.ledger import ExperimentLedger, LedgerTamperedError
from sentinelle.agents.llm import ClaudeLLM, LLMOutputError, LLMRefusal
from sentinelle.agents.pipeline import PAPER_ONLY, REJECTED, ResearchPipeline
from sentinelle.agents.roles import CRITIC_POINTS, CriticReport, OperatorReport
from sentinelle.backtest.leakage import check_no_lookahead
from sentinelle.strategy.freqtrade_export import class_name, render_config, render_strategy
from sentinelle.strategy.spec import StrategySpec, compile_signal
from tests.conftest import make_prices

BASE = dict(
    name="mom_roc",
    asset="BTC/USDT",
    timeframe="1d",
    mechanism="Les flux de suivi de tendance prolongent les mouvements de court terme.",
    counterparty="vendeurs paniqués et liquidations",
    invalidation="deux mois sans persistance des rendements",
    entry_all=[{"left": {"kind": "roc", "window": "w"}, "op": ">", "value": 0.0}],
    exit_any=[{"left": {"kind": "roc", "window": "w"}, "op": "<", "value": 0.0}],
    stop_loss_pct=0.10,
    param_grid={"w": [2, 3]},
)


def momentum_prices(n=1500, seed=4, phi=0.25, vol=0.02) -> pd.Series:
    """Rendements autocorrélés : un edge de momentum réel, implanté volontairement."""
    rng = np.random.default_rng(seed)
    e = rng.normal(0, vol, n)
    r = np.zeros(n)
    for i in range(1, n):
        r[i] = phi * r[i - 1] + e[i]
    r += 0.002 * np.sin(np.arange(n) / 120)
    idx = pd.date_range("2021-01-01", periods=n, freq="D", tz="UTC")
    return pd.Series(20_000 * np.exp(np.cumsum(r)), index=idx)


# --- DSL ---------------------------------------------------------------------------
def test_spec_valid_and_grid():
    spec = StrategySpec(**BASE)
    assert spec.grid() == [{"w": 2}, {"w": 3}]


@pytest.mark.parametrize(
    "patch",
    [
        {"asset": "PEPE/USDT"},
        {"param_grid": {}},  # paramètre référencé mais non défini
        {"param_grid": {"w": [2, 3], "inutile": [5, 6]}},
        {"param_grid": {"w": list(range(2, 40))}},  # grille trop grande
        {"stop_loss_pct": 0.5},
        {"mechanism": "momentum"},  # mécanisme trop vague
        {"entry_all": [{"left": {"kind": "close"}, "op": ">", "value": 1.0, "right": {"kind": "sma", "window": 5}}]},
    ],
)
def test_spec_rejects_unsafe_or_vague(patch):
    with pytest.raises(ValidationError):
        StrategySpec(**{**BASE, **patch})


def test_spec_forbids_extra_fields_like_leverage():
    with pytest.raises(ValidationError):
        StrategySpec(**{**BASE, "leverage": 5})


@pytest.mark.parametrize("kind", ["sma", "ema", "rsi", "roc", "rolling_max", "rolling_min", "volatility"])
def test_every_indicator_is_past_only(kind):
    spec = StrategySpec(
        **{
            **BASE,
            "entry_all": [{"left": {"kind": "close"}, "op": ">", "right": {"kind": kind, "window": 10}}],
            "exit_any": [{"left": {"kind": "close"}, "op": "<", "right": {"kind": kind, "window": 10}}],
            "param_grid": {},
        }
    )
    assert check_no_lookahead(compile_signal(spec, {}), make_prices(400)).passed


def test_stop_loss_exits_position():
    idx = pd.date_range("2024-01-01", periods=6, freq="D", tz="UTC")
    close = pd.Series([100, 101, 102, 90, 95, 96], index=idx, dtype=float)
    spec = StrategySpec(**{**BASE, "entry_all": [{"left": {"kind": "close"}, "op": ">", "value": 100.5}],
                           "exit_any": [{"left": {"kind": "close"}, "op": ">", "value": 1e9}], "param_grid": {}})
    sig = compile_signal(spec, {})(close)
    assert list(sig) == [0, 1, 1, 0, 0, 0]  # 90 <= 101 × 0,9 → stop


# --- Journal ---------------------------------------------------------------------------
def test_ledger_counts_trials_and_detects_tampering(tmp_path):
    ledger = ExperimentLedger(tmp_path / "l.jsonl")
    ledger.append("hypothesis", {"name": "a"}, trials=4)
    ledger.append("hypothesis", {"name": "b"}, trials=2)
    assert ledger.total_trials() == 6
    lines = (tmp_path / "l.jsonl").read_text().splitlines()
    forged = json.loads(lines[0])
    forged["trials"] = 1  # tentative de réduire N après coup
    (tmp_path / "l.jsonl").write_text(json.dumps(forged) + "\n" + lines[1] + "\n")
    with pytest.raises(LedgerTamperedError):
        ledger.total_trials()


def test_ledger_detects_deleted_entry(tmp_path):
    ledger = ExperimentLedger(tmp_path / "l.jsonl")
    for name in "abc":
        ledger.append("hypothesis", {"name": name}, trials=1)
    lines = (tmp_path / "l.jsonl").read_text().splitlines()
    (tmp_path / "l.jsonl").write_text(lines[0] + "\n" + lines[2] + "\n")
    with pytest.raises(LedgerTamperedError):
        ledger.verify()


# --- Client Claude (sans réseau) -----------------------------------------------------------
class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def fake_client(response):
    msgs = FakeMessages(response)
    return SimpleNamespace(beta=SimpleNamespace(messages=msgs)), msgs


def test_claude_llm_request_shape():
    report = OperatorReport(title="t", summary="s", details="d")
    client, msgs = fake_client(SimpleNamespace(stop_reason="end_turn", parsed_output=report))
    out = ClaudeLLM(client=client).structured("sys", "user", OperatorReport)
    assert out == report
    assert msgs.kwargs["model"] == "claude-opus-5-5"
    assert msgs.kwargs["fallbacks"] == "default"
    assert msgs.kwargs["betas"] == ["server-side-fallback-2026-07-01"]
    assert msgs.kwargs["output_format"] is OperatorReport
    assert "tools" not in msgs.kwargs  # aucun outil donné aux agents


@pytest.mark.parametrize(
    "resp,exc",
    [
        (SimpleNamespace(stop_reason="refusal", stop_details=None, parsed_output=None), LLMRefusal),
        (SimpleNamespace(stop_reason="max_tokens", parsed_output=None), LLMOutputError),
        (SimpleNamespace(stop_reason="end_turn", parsed_output=None), LLMOutputError),
    ],
)
def test_claude_llm_failures(resp, exc):
    client, _ = fake_client(resp)
    with pytest.raises(exc):
        ClaudeLLM(client=client).structured("s", "u", OperatorReport)


# --- Pipeline -----------------------------------------------------------------------------------
class FakeLLM:
    def __init__(self, spec=BASE, critic_verdict="VALIDE", present=None):
        self.spec, self.critic_verdict, self.present = spec, critic_verdict, present
        self.calls = []

    def structured(self, system, user, schema):
        self.calls.append(schema.__name__)
        if schema is StrategySpec:
            return StrategySpec(**self.spec)
        if schema is CriticReport:
            items = [{"point": p, "status": "PRESENT" if p == self.present else "ABSENT", "evidence": "cité"} for p in CRITIC_POINTS]
            return CriticReport(items=items, economic_mechanism_credible=True, verdict=self.critic_verdict, main_reason="raison")
        return OperatorReport(title="Rapport", summary="Résumé", details="Détails")


def test_pipeline_rejects_random_walk(tmp_path):
    prices = make_prices(1500, seed=11)
    out = ResearchPipeline(FakeLLM(), {("BTC/USDT", "1d"): prices}, tmp_path).run(1)[0]
    assert out.decision == REJECTED
    assert (tmp_path / "strategies" / "mom_roc" / "rapport.md").exists()
    assert not (tmp_path / "strategies" / "mom_roc" / "freqtrade").exists()


def test_pipeline_promotes_real_edge_to_paper_only(tmp_path):
    out = ResearchPipeline(FakeLLM(), {("BTC/USDT", "1d"): momentum_prices()}, tmp_path).run(1)[0]
    assert out.decision == PAPER_ONLY, out.reason
    assert out.gates == {"gate1": "PASS", "gate2": "PASS", "gate3": "PASS"}
    ft = tmp_path / "strategies" / "mom_roc" / "freqtrade"
    config = json.loads((ft / "config.dryrun.json").read_text())
    assert config["dry_run"] is True and config["trading_mode"] == "spot"
    assert config["exchange"]["key"] == "" and config["exchange"]["secret"] == ""


def test_critic_present_blocks_even_a_real_edge(tmp_path):
    llm = FakeLLM(present="look_ahead")
    out = ResearchPipeline(llm, {("BTC/USDT", "1d"): momentum_prices()}, tmp_path).run(1)[0]
    assert out.decision == REJECTED and out.gates["gate1"] == "REJECT"


def test_same_idea_cannot_be_retested_and_trials_accumulate(tmp_path):
    pipe = ResearchPipeline(FakeLLM(), {("BTC/USDT", "1d"): make_prices(1500, seed=11)}, tmp_path)
    first, second = pipe.run(2)
    assert "déjà testé" in second.reason
    assert pipe.ledger.total_trials() == 2  # la grille {"w": [2, 3]} comptée une fois


def test_global_trial_count_makes_gate2_harder(tmp_path):
    ledger = ExperimentLedger(tmp_path / "ledger.jsonl")
    ledger.append("hypothesis", {"name": "anciens_essais"}, trials=5000)
    out = ResearchPipeline(FakeLLM(), {("BTC/USDT", "1d"): momentum_prices()}, tmp_path).run(1)[0]
    assert out.dossier["gate2"]["n_trials"] == 5002


def test_missing_market_data_rejected(tmp_path):
    out = ResearchPipeline(FakeLLM(spec={**BASE, "asset": "ETH/USDT"}), {("BTC/USDT", "1d"): momentum_prices()}, tmp_path).run(1)[0]
    assert out.decision == REJECTED and "Pas de données" in out.reason


# --- Export Freqtrade : parité avec le backtest ---------------------------------------------------
@pytest.fixture
def fake_freqtrade(monkeypatch):
    mod = types.ModuleType("freqtrade")
    strat = types.ModuleType("freqtrade.strategy")
    strat.IStrategy = type("IStrategy", (), {})
    monkeypatch.setitem(sys.modules, "freqtrade", mod)
    monkeypatch.setitem(sys.modules, "freqtrade.strategy", strat)


def test_freqtrade_strategy_matches_backtest_signals(tmp_path, fake_freqtrade):
    spec = StrategySpec(**{
        **BASE,
        "entry_all": [
            {"left": {"kind": "ema", "window": "fast"}, "op": ">", "right": {"kind": "sma", "window": 50}},
            {"left": {"kind": "rsi", "window": 14}, "op": "<", "value": 70.0},
        ],
        "exit_any": [{"left": {"kind": "close"}, "op": "<", "right": {"kind": "rolling_min", "window": 20}}],
        "param_grid": {"fast": [10, 20]},
        "stop_loss_pct": 0.15,
    })
    params = {"fast": 20}
    src = render_strategy(spec, params)
    path = tmp_path / "gen.py"
    path.write_text(src)
    module_spec = importlib.util.spec_from_file_location("gen", path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    strategy = getattr(module, class_name(spec))()
    assert strategy.can_short is False and strategy.stoploss == pytest.approx(-0.15)

    close = make_prices(500, seed=5)
    df = pd.DataFrame({"close": close.to_numpy()})
    df = strategy.populate_entry_trend(strategy.populate_exit_trend(df, {}), {})
    bot_entry = df["enter_long"].fillna(0).astype(bool).to_numpy()
    bot_exit = df["exit_long"].fillna(0).astype(bool).to_numpy()

    from sentinelle.strategy.spec import evaluate_condition

    entry = np.logical_and.reduce([evaluate_condition(c, close, params).to_numpy() for c in spec.entry_all])
    exit_ = np.logical_or.reduce([evaluate_condition(c, close, params).to_numpy() for c in spec.exit_any])
    assert (bot_entry == (entry & ~exit_)).all()
    assert (bot_exit == exit_).all()
    assert bot_entry.any() and bot_exit.any()


def test_freqtrade_config_has_no_secrets_and_is_dry_run():
    cfg = json.loads(render_config(StrategySpec(**BASE), 100.0))
    assert cfg["dry_run"] and cfg["trading_mode"] == "spot"
    assert cfg["stake_amount"] == 20.0  # 20 % du portefeuille simulé
    assert cfg["api_server"]["password"] == "" and cfg["telegram"]["token"] == ""
