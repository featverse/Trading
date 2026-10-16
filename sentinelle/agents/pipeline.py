"""ORCHESTRATEUR — pipeline séquentiel de recherche (règle ORCHESTRA-IA : un agent
après l'autre, chaque gate bloque la suite).

HYPOTHESIS → GATE 1 (troncature + CRITIC) → GATE 2 (DSR, N global) → GATE 3 (walk-forward)
→ RISK → décision → rapport.

Décisions possibles : REJECTED ou PAPER_TRADING_ONLY. Le pipeline ne peut JAMAIS mettre
une stratégie en argent réel : cela exige le dry-run puis la validation humaine.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pydantic import ValidationError

from sentinelle.agents.ledger import ExperimentLedger
from sentinelle.agents.llm import LLMOutputError, LLMRefusal, StructuredLLM
from sentinelle.agents.roles import critique, propose_hypothesis, write_report
from sentinelle.backtest.engine import CostModel, run_backtest
from sentinelle.backtest.leakage import check_no_lookahead
from sentinelle.backtest.metrics import PERIODS_PER_YEAR, compute_metrics, sharpe_per_period
from sentinelle.backtest.walkforward import regime_breakdown, regime_labels, walk_forward
from sentinelle.config import RiskLimits
from sentinelle.stats.dsr import deflated_sharpe_ratio
from sentinelle.strategy.freqtrade_export import render_config, render_readme, render_strategy
from sentinelle.strategy.spec import StrategySpec, compile_signal

REJECTED = "REJECTED"
PAPER_ONLY = "PAPER_TRADING_ONLY"

# Fenêtres walk-forward par timeframe : (train, test) en barres ≈ 180 j / 60 j.
WF_WINDOWS = {"1d": (180, 60), "4h": (180 * 6, 60 * 6)}


@dataclass
class StrategyOutcome:
    name: str
    decision: str
    reason: str
    gates: dict[str, str] = field(default_factory=dict)
    dossier: dict[str, Any] = field(default_factory=dict)


def _risk_review(spec: StrategySpec, limits: RiskLimits, backtest_mdd: float) -> dict[str, Any]:
    losses = {n: float(1 - (1 - limits.risk_per_trade) ** n) for n in (10, 12, 15, 20)}
    return {
        "risk_per_trade": limits.risk_per_trade,
        "stop_loss_pct": spec.stop_loss_pct,
        "max_position_pct": limits.max_position_pct,
        "drawdown_after_consecutive_losses": losses,
        "kill_conditions": {
            "max_drawdown_absolute": -limits.max_drawdown,
            "max_drawdown_vs_backtest": 1.5 * backtest_mdd,
            "live_sharpe_30d_below": "50 % du Sharpe walk-forward",
            "daily_loss_limit": -limits.daily_loss_limit,
        },
    }


class ResearchPipeline:
    def __init__(
        self,
        llm: StructuredLLM,
        prices: dict[tuple[str, str], pd.Series],
        workdir: str | Path,
        limits: RiskLimits = RiskLimits(),
        costs: CostModel = CostModel(),
        dry_run_wallet_usdt: float = 100.0,
    ):
        """`prices` : {(asset, timeframe): clôtures UTC}."""
        self.llm = llm
        self.prices = prices
        self.workdir = Path(workdir)
        self.ledger = ExperimentLedger(self.workdir / "ledger.jsonl")
        self.limits = limits
        self.costs = costs
        self.wallet = dry_run_wallet_usdt

    # --- Orchestration --------------------------------------------------------------
    def run(self, n_ideas: int = 1) -> list[StrategyOutcome]:
        self.ledger.verify()
        outcomes = []
        for _ in range(n_ideas):
            outcome = self.run_one()
            outcomes.append(outcome)
            self.ledger.append("decision", {"name": outcome.name, "decision": outcome.decision, "reason": outcome.reason})
        return outcomes

    def _context(self) -> dict[str, Any]:
        tested = [
            {"name": e["payload"]["name"], "decision": e["payload"]["decision"], "reason": e["payload"]["reason"]}
            for e in self.ledger.entries()
            if e["kind"] == "decision"
        ]
        return {
            "marchés_disponibles": [f"{a} {tf}" for (a, tf) in self.prices],
            "frais_et_slippage_bps": self.costs.total_bps,
            "essais_déjà_comptés_N": self.ledger.total_trials(),
            "stratégies_déjà_testées": tested[-30:],
            "contrainte": "spot long uniquement, risque 1 % max par trade, petit capital",
        }

    def run_one(self) -> StrategyOutcome:
        # ── AGENT HYPOTHESIS ─────────────────────────────────────────────────────────
        try:
            spec = propose_hypothesis(self.llm, self._context())
        except (LLMRefusal, LLMOutputError, ValidationError) as exc:
            return StrategyOutcome("(aucune)", REJECTED, f"Hypothèse inexploitable : {exc}")
        if spec.name in self.ledger.strategy_names():
            return StrategyOutcome(spec.name, REJECTED, "Nom déjà testé : une même idée ne repasse pas.")
        key = (spec.asset, spec.timeframe)
        if key not in self.prices:
            return StrategyOutcome(spec.name, REJECTED, f"Pas de données pour {spec.asset} {spec.timeframe}.")
        prices = self.prices[key]
        grid = spec.grid()
        # Chaque variante est comptée AVANT d'en voir le résultat.
        self.ledger.append("hypothesis", {"name": spec.name, "spec": spec.model_dump()}, trials=len(grid))
        dossier: dict[str, Any] = {"spec": spec.model_dump(), "data": {"asset": spec.asset, "timeframe": spec.timeframe,
                                   "bars": len(prices), "start": str(prices.index[0]), "end": str(prices.index[-1])}}
        gates: dict[str, str] = {}

        # ── GATE 1 : anti-fuite (automatique + CRITIC LLM) ─────────────────────────
        leak_reports = {json.dumps(p): check_no_lookahead(compile_signal(spec, p), prices) for p in grid}
        leak_ok = all(r.passed for r in leak_reports.values())
        has_bull_and_bear = set(regime_labels(prices).unique()) >= {"bull", "bear"}
        evidence = {
            "test_troncature": {k: {"passed": r.passed, "failures": r.failures[:2]} for k, r in leak_reports.items()},
            "execution": "signal à la clôture t, position en t+1 (shift(1)) ; spot, exposition 0..1",
            "couts": f"frais {self.costs.fee_bps} bps + slippage {self.costs.slippage_bps} bps sur le turnover",
            "stop": "évalué à la clôture dans le backtest ; posé sur l'exchange en réel",
            "univers": f"actif unique {spec.asset}, toujours coté (pas d'univers multi-actifs)",
            "donnees": f"clôtures Binance UTC, {len(prices)} barres {spec.timeframe}",
            "regimes_presents": sorted(set(regime_labels(prices).unique())),
            "nombre_variantes": len(grid),
            "essais_totaux_N": self.ledger.total_trials(),
        }
        dossier["gate1_evidence"] = evidence
        if not leak_ok:
            gates["gate1"] = "REJECT"
            return self._finish(spec, REJECTED, "GATE 1 : fuite de données détectée par le test de troncature.", gates, dossier)
        if not has_bull_and_bear:
            gates["gate1"] = "REJECT"
            return self._finish(spec, REJECTED, "GATE 1 : l'historique ne contient pas à la fois un marché haussier et baissier.", gates, dossier)
        try:
            critic = critique(self.llm, spec, evidence)
        except (LLMRefusal, LLMOutputError) as exc:
            gates["gate1"] = "REJECT"
            return self._finish(spec, REJECTED, f"GATE 1 : critique indisponible ({exc}) — on ne valide pas sans audit.", gates, dossier)
        dossier["critic"] = critic.model_dump()
        if critic.rejects():
            gates["gate1"] = "REJECT"
            return self._finish(spec, REJECTED, f"GATE 1 (Critic) : {critic.main_reason}", gates, dossier)
        gates["gate1"] = "PASS"

        # ── GATE 2 : Deflated Sharpe, N = tous les essais du programme ──────────────
        ppy = PERIODS_PER_YEAR[spec.timeframe]
        runs = {json.dumps(p): run_backtest(prices, compile_signal(spec, p)(prices), self.costs) for p in grid}
        trial_sr = [sharpe_per_period(bt["net"]) for bt in runs.values()]
        best_key = list(runs)[int(np.argmax(trial_sr))]
        m = compute_metrics(runs[best_key], ppy)
        n_total = self.ledger.total_trials()
        dsr = deflated_sharpe_ratio(m["sharpe_per_period"], trial_sr, int(m["n_obs"]), m["skewness"], m["kurtosis"], n_trials=n_total)
        bh = compute_metrics(run_backtest(prices, pd.Series(1.0, index=prices.index), self.costs), ppy)
        dossier["in_sample"] = {"best_params": json.loads(best_key), "metrics": m, "buy_and_hold": bh}
        dossier["gate2"] = {"explain": dsr.explain(), "dsr": dsr.dsr, "n_trials": n_total}
        if m["sharpe_annualized"] > 2.0:
            gates["gate2"] = "REJECT"
            return self._finish(spec, REJECTED, "GATE 2 : Sharpe > 2 en crypto, fuite présumée jusqu'à preuve du contraire.", gates, dossier)
        if not dsr.passed:
            gates["gate2"] = "REJECT"
            return self._finish(spec, REJECTED, f"GATE 2 : {dsr.explain()}", gates, dossier)
        gates["gate2"] = "PASS"

        # ── GATE 3 : walk-forward hors échantillon ───────────────────────────────────
        train, test = WF_WINDOWS[spec.timeframe]
        warmup = min(train, max(spec.max_window(p) for p in grid) + 5)
        # Seuils au niveau du COMPTE : une position pèse au plus max_position_pct du capital.
        # Pire fold toléré pour le compte = moitié du kill switch.
        exposure = self.limits.max_position_pct
        worst_fold_strategy = (self.limits.max_drawdown / 2) / exposure
        try:
            wf = walk_forward(prices, lambda p: compile_signal(spec, p), grid, train, test, ppy, warmup, self.costs,
                              max_worst_fold_loss=worst_fold_strategy)
        except ValueError as exc:
            gates["gate3"] = "REJECT"
            return self._finish(spec, REJECTED, f"GATE 3 : {exc}", gates, dossier)
        regimes = regime_breakdown(wf.oos_net, regime_labels(prices))
        dossier["gate3"] = {
            "folds": wf.folds.assign(test_start=wf.folds["test_start"].astype(str), test_end=wf.folds["test_end"].astype(str)).to_dict("records"),
            "positive_fold_ratio": wf.positive_fold_ratio,
            "account_exposure": exposure,
            "worst_fold_account_estimate": wf.worst_fold_return * exposure,
            "worst_fold_return": wf.worst_fold_return,
            "reasons": wf.reasons,
            "regimes": regimes.reset_index().to_dict("records"),
        }
        if not wf.passed:
            gates["gate3"] = "REJECT"
            return self._finish(spec, REJECTED, "GATE 3 : " + " ".join(wf.reasons), gates, dossier)
        gates["gate3"] = "PASS"

        # ── RISK / CRO ─────────────────────────────────────────────────────────────
        oos_equity = np.exp(wf.oos_net.cumsum())
        oos_mdd = float((oos_equity / oos_equity.cummax() - 1).min())
        account_mdd = oos_mdd * exposure
        dossier["risk"] = _risk_review(spec, self.limits, account_mdd)
        dossier["risk"]["oos_max_drawdown_strategy"] = oos_mdd
        dossier["risk"]["oos_max_drawdown_account_estimate"] = account_mdd
        if account_mdd < -0.8 * self.limits.max_drawdown:
            return self._finish(spec, REJECTED, f"RISK : drawdown hors échantillon estimé à {account_mdd:.1%} du compte, trop proche du kill switch.", gates, dossier)

        # Paramètres retenus pour le dry-run : ceux du dernier fold (les plus récents).
        live_params = wf.folds["params"].iloc[-1]
        dossier["paper_params"] = live_params
        return self._finish(spec, PAPER_ONLY, "Les 3 gates sont passées : simulation (dry-run) uniquement.", gates, dossier, live_params)

    # --- Sorties ----------------------------------------------------------------------
    def _finish(self, spec, decision, reason, gates, dossier, params=None) -> StrategyOutcome:
        outdir = self.workdir / "strategies" / spec.name
        outdir.mkdir(parents=True, exist_ok=True)
        dossier.update({"decision": decision, "reason": reason, "gates": gates})
        (outdir / "dossier.json").write_text(json.dumps(dossier, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        try:
            report = write_report(self.llm, dossier)
            text = f"# {report.title}\n\n{report.summary}\n\n{report.details}\n"
        except (LLMRefusal, LLMOutputError) as exc:
            text = f"# {spec.name}\n\nDécision : {decision}\n\n{reason}\n\n(Rapport rédigé indisponible : {exc})\n"
        (outdir / "rapport.md").write_text(text, encoding="utf-8")
        if decision == PAPER_ONLY and params is not None:
            ft = outdir / "freqtrade"
            ft.mkdir(exist_ok=True)
            from sentinelle.strategy.freqtrade_export import class_name

            (ft / f"{class_name(spec)}.py").write_text(render_strategy(spec, params, self.limits), encoding="utf-8")
            (ft / "config.dryrun.json").write_text(render_config(spec, self.wallet, self.limits), encoding="utf-8")
            (ft / "README.md").write_text(render_readme(spec, params), encoding="utf-8")
        return StrategyOutcome(spec.name, decision, reason, gates, dossier)
