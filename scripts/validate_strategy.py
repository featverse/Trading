"""Fait passer une stratégie par le pipeline complet : GATE 1 → GATE 2 → GATE 3 → RISK.

Usage :
    python scripts/validate_strategy.py                 # télécharge BTCUSDT daily chez Binance
    python scripts/validate_strategy.py --csv btc.csv   # ou depuis un fichier
    python scripts/validate_strategy.py --synthetic     # données simulées (test hors ligne)

Exemple livré : croisement prix / moyenne mobile (« trend following »).
Mécanisme supposé : les flux de suivi de tendance et la lenteur de diffusion de l'information
prolongent les mouvements ; contrepartie = vendeurs pressés / short squeezes. À invalider.

Illustratif, pas un conseil financier. Aucune garantie de performance.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sentinelle.backtest.engine import CostModel, run_backtest  # noqa: E402
from sentinelle.backtest.leakage import check_no_lookahead  # noqa: E402
from sentinelle.backtest.metrics import compute_metrics, sharpe_per_period  # noqa: E402
from sentinelle.backtest.walkforward import regime_breakdown, regime_labels, walk_forward  # noqa: E402
from sentinelle.data import fetch_binance_closes, load_csv_closes  # noqa: E402
from sentinelle.stats.dsr import deflated_sharpe_ratio  # noqa: E402

GRID = [{"window": w} for w in (20, 50, 100, 150, 200)]


def factory(params):
    w = params["window"]
    return lambda p: (p > p.rolling(w).mean()).astype(float)


def load(args) -> tuple[pd.Series, str]:
    if args.csv:
        return load_csv_closes(args.csv), f"CSV {args.csv}"
    if not args.synthetic:
        try:
            return fetch_binance_closes("BTCUSDT", "1d", 1000), "Binance BTCUSDT 1d"
        except Exception as exc:  # réseau indisponible
            print(f"[!] Téléchargement Binance impossible ({exc}) → données simulées.")
    rng = np.random.default_rng(42)
    idx = pd.date_range("2023-01-01", periods=1000, freq="D", tz="UTC")
    r = rng.normal(0.0005, 0.03, len(idx))
    r[0] = 0
    return pd.Series(30_000 * np.exp(np.cumsum(r)), index=idx), "SIMULÉES (marche aléatoire)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv")
    ap.add_argument("--synthetic", action="store_true")
    args = ap.parse_args()

    prices, source = load(args)
    costs = CostModel(fee_bps=10, slippage_bps=5)
    print(f"Données : {source} — {len(prices)} barres, {prices.index[0].date()} → {prices.index[-1].date()}\n")

    verdicts: dict[str, str] = {}

    # GATE 1 — fuite
    leak_ok = all(check_no_lookahead(factory(p), prices).passed for p in GRID)
    verdicts["GATE 1 anti-fuite"] = "PASS" if leak_ok else "REJECT"

    # GATE 2 — Deflated Sharpe sur TOUS les essais (sélection in-sample)
    runs = {p["window"]: run_backtest(prices, factory(p)(prices), costs) for p in GRID}
    trial_sr = [sharpe_per_period(bt["net"]) for bt in runs.values()]
    best_w = list(runs)[int(np.argmax(trial_sr))]
    m = compute_metrics(runs[best_w], 365)
    dsr = deflated_sharpe_ratio(m["sharpe_per_period"], trial_sr, int(m["n_obs"]), m["skewness"], m["kurtosis"])
    verdicts["GATE 2 Deflated Sharpe"] = "PASS" if dsr.passed else "REJECT"
    print(f"Meilleur in-sample : SMA{best_w} | Sharpe ann. {m['sharpe_annualized']:.2f} | "
          f"rendement {m['total_return']:.1%} | max DD {m['max_drawdown']:.1%}")
    if m["sharpe_annualized"] > 2:
        print("  [!] Sharpe > 2 en daily crypto : fuite présumée jusqu'à preuve du contraire.")
    print("  " + dsr.explain())

    # GATE 3 — walk-forward
    wf = walk_forward(prices, factory, GRID, train_bars=180, test_bars=60, periods_per_year=365,
                      warmup_bars=180, costs=costs)
    verdicts["GATE 3 walk-forward"] = "PASS" if wf.passed else "REJECT"
    print(f"\nWalk-forward : {len(wf.folds)} folds | folds positifs {wf.positive_fold_ratio:.0%} | "
          f"pire fold {wf.worst_fold_return:.1%} | N essais cumulés {wf.n_trials}")
    for r in wf.reasons:
        print(f"  - {r}")
    print("\nPar régime (hors échantillon) :")
    print(regime_breakdown(wf.oos_net, regime_labels(prices)).round(4).to_string())

    # Buy & hold pour comparaison
    bh = compute_metrics(run_backtest(prices, pd.Series(1.0, index=prices.index), costs), 365)
    print(f"\nRéférence buy & hold : rendement {bh['total_return']:.1%} | max DD {bh['max_drawdown']:.1%}")

    print("\n================ VERDICT ================")
    for k, v in verdicts.items():
        print(f"{k:<26} {v}")
    final = "PAPER-TRADING ONLY" if all(v == "PASS" for v in verdicts.values()) else "STRATÉGIE REJETÉE"
    print(f"{'DÉCISION':<26} {final}")
    print("\nIllustratif, pas un conseil financier. Aucune garantie de performance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
