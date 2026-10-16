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

## Phase 2 : l'équipe d'agents de recherche

| Module | Rôle |
|---|---|
| `sentinelle/strategy/spec.py` | Langage de stratégie déclaratif : l'IA produit des **données validées, jamais du code** |
| `sentinelle/strategy/indicators.py` | Indicateurs « passé uniquement » partagés par le backtest et le bot |
| `sentinelle/agents/roles.py` | Agents Claude : **Hypothesis**, **Critic** hostile, **Rédacteur** (aucun outil, aucune clé) |
| `sentinelle/agents/pipeline.py` | **Orchestrateur** séquentiel : Hypothèse → Gate 1 → Gate 2 → Gate 3 → Risk → décision |
| `sentinelle/agents/ledger.py` | Journal immuable chaîné par hash : N essais global, rejets conservés |
| `sentinelle/strategy/freqtrade_export.py` | Génère le bot Freqtrade + config **DRY-RUN** pour une stratégie validée |
| `deploy/` | Docker Compose du bot en simulation, `.env.example` (secrets hors Git) |

Décisions possibles : `REJECTED` ou `PAPER_TRADING_ONLY`. **Le pipeline ne peut jamais engager d'argent réel.**

```bash
.venv/bin/python scripts/run_research.py --demo          # sans clé API
ANTHROPIC_API_KEY=... .venv/bin/python scripts/run_research.py --ideas 3
```

## Phase 3 : le serveur et l'application Android

| Élément | Rôle |
|---|---|
| `sentinelle/api/app.py` | API sécurisée : tableau de bord, stratégies, risque, apports, arrêt d'urgence |
| `sentinelle/api/supervisor.py` | Superviseur : relie bot ↔ gardien ↔ paliers, détecte apports et retraits automatiquement |
| `sentinelle/api/security.py` | Mot de passe scrypt, jetons signés courts + rotation, verrouillage après 5 échecs |
| Bot généré | Demande l'accord du gardien avant **chaque** achat (refus si pas de réponse) ; taille selon la règle du 1 % |
| `mobile/sentinelle_app/` | Application Android (Flutter) : empreinte, Keystore, HTTPS obligatoire |
| `deploy/` | Docker Compose : bot + serveur + HTTPS automatique (Caddy) |
| `.github/workflows/ci.yml` | Tests à chaque envoi + **APK Android téléchargeable** |

Installation pas à pas : [`docs/INSTALLATION.md`](docs/INSTALLATION.md).

## Lancer

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q                                # 105 tests
.venv/bin/python scripts/validate_strategy.py                # pipeline complet sur BTCUSDT daily
.venv/bin/python scripts/validate_strategy.py --synthetic    # hors ligne
```

## Règles qui ne changent jamais
Spot uniquement · levier 1 · stop-loss obligatoire · pas de martingale · le kill switch ne se lève qu'avec l'opérateur · l'argent mis à l'abri ne revient jamais au trading.
