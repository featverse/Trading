# SENTINELLE — IA de trading crypto spot (Binance)

> Le capital d'abord, la performance ensuite. Illustratif, pas un conseil financier. Aucune garantie de performance.

Conception complète : [`docs/CONCEPTION_APP_TRADING_IA.md`](docs/CONCEPTION_APP_TRADING_IA.md).

## Phase 1 (ce dépôt) : fondations

| Module | Rôle |
|---|---|
| `sentinelle/config.py` | Plafonds absolus non configurables (spot, levier 1, risque ≤ 1 %, DD ≤ 10 %) |
| `sentinelle/backtest/engine.py` | Moteur de backtest « inviolable » : `shift(1)`, frais + slippage sur turnover, UTC |
| `sentinelle/backtest/leakage.py` | **GATE 1** : détection automatique de look-ahead / repainting (test de troncature) |
| `sentinelle/stats/dsr.py` | **GATE 2** : Deflated Sharpe Ratio sur le nombre réel d'essais |
| `sentinelle/backtest/walkforward.py` | **GATE 3** : walk-forward hors échantillon et analyse bull / bear / chop |
| `sentinelle/risk/sizing.py` | Taille = Capital × Risque % / (Entrée − Stop), minimum de l'exchange |
| `sentinelle/risk/guard.py` | Gardien indépendant : coupe-circuit journalier, kill switch, redémarrage manuel |
| `sentinelle/risk/tiers.py` | Paliers FCFA (P0 → P3) et mise à l'abri des gains |

## Lancer

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q                                # 54 tests
.venv/bin/python scripts/validate_strategy.py                # pipeline complet sur BTCUSDT daily
.venv/bin/python scripts/validate_strategy.py --synthetic    # hors ligne
```

## Règles qui ne changent jamais
Spot uniquement · levier 1 · stop-loss obligatoire · pas de martingale · le kill switch ne se lève qu'avec l'opérateur · l'argent mis à l'abri ne revient jamais au trading.
