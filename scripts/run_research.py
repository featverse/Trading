"""Lance un cycle de recherche de l'équipe d'agents.

Usage (sur le VPS) :
    export ANTHROPIC_API_KEY=...            # jamais dans le code ni dans Git
    python scripts/run_research.py --ideas 3
    python scripts/run_research.py --demo   # sans clé API ni réseau (agents simulés)

Résultats dans ./research/ :
    ledger.jsonl                         journal immuable de tous les essais
    strategies/<nom>/rapport.md          rapport en français
    strategies/<nom>/dossier.json        preuves complètes des 3 gates
    strategies/<nom>/freqtrade/          (seulement si PAPER_TRADING_ONLY) bot DRY-RUN

Illustratif, pas un conseil financier. Aucune garantie de performance.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sentinelle.agents.pipeline import ResearchPipeline  # noqa: E402
from sentinelle.data import fetch_binance_closes  # noqa: E402

MARKETS = [("BTC/USDT", "1d"), ("ETH/USDT", "1d"), ("BTC/USDT", "4h"), ("ETH/USDT", "4h")]


def load_markets() -> dict:
    data = {}
    for asset, tf in MARKETS:
        try:
            data[(asset, tf)] = fetch_binance_closes(asset.replace("/", ""), tf, 1000)
        except Exception as exc:
            print(f"[!] {asset} {tf} indisponible : {exc}")
    return data


class DemoLLM:
    """Agents simulés pour tester l'installation sans clé API."""

    def structured(self, system, user, schema):
        from sentinelle.agents.roles import CRITIC_POINTS, CriticReport, OperatorReport
        from sentinelle.strategy.spec import StrategySpec

        if schema is StrategySpec:
            return StrategySpec(
                name="demo_trend_ema",
                asset="BTC/USDT",
                timeframe="1d",
                mechanism="Les fonds de suivi de tendance achètent après les hausses et prolongent les mouvements.",
                counterparty="vendeurs précoces et positions short liquidées",
                invalidation="plus de trois faux signaux consécutifs en marché sans tendance",
                entry_all=[{"left": {"kind": "close"}, "op": ">", "right": {"kind": "ema", "window": "w"}}],
                exit_any=[{"left": {"kind": "close"}, "op": "<", "right": {"kind": "ema", "window": "w"}}],
                stop_loss_pct=0.08,
                param_grid={"w": [20, 50]},
            )
        if schema is CriticReport:
            return CriticReport(
                items=[{"point": p, "status": "ABSENT", "evidence": "démo"} for p in CRITIC_POINTS],
                economic_mechanism_credible=True, verdict="VALIDE", main_reason="démo",
            )
        return OperatorReport(title="Rapport de démonstration", summary="Agents simulés.", details="Voir dossier.json.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ideas", type=int, default=1)
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--workdir", default="research")
    ap.add_argument("--wallet-usdt", type=float, default=100.0, help="Portefeuille simulé du dry-run")
    args = ap.parse_args()

    if args.demo:
        rng = np.random.default_rng(0)
        idx = pd.date_range("2023-01-01", periods=1000, freq="D", tz="UTC")
        r = rng.normal(0.0004, 0.03, len(idx))
        r[0] = 0
        data = {("BTC/USDT", "1d"): pd.Series(30_000 * np.exp(np.cumsum(r)), index=idx)}
        llm = DemoLLM()
    else:
        from sentinelle.agents.llm import ClaudeLLM

        data = load_markets()
        if not data:
            print("Aucune donnée de marché : arrêt.")
            return 1
        llm = ClaudeLLM()

    pipeline = ResearchPipeline(llm, data, args.workdir, dry_run_wallet_usdt=args.wallet_usdt)
    for out in pipeline.run(args.ideas):
        print(f"{out.name:<28} {out.decision:<20} {out.gates} — {out.reason}")
    print(f"\nEssais cumulés (N) : {pipeline.ledger.total_trials()}  |  journal : {pipeline.ledger.path}")
    print("Illustratif, pas un conseil financier. Aucune garantie de performance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
