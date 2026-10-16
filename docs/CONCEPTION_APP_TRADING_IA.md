# CONCEPTION — Application mobile « Trading IA autonome » (nom de travail : **SENTINELLE**)

> Document de conception, version 0.1. Il est construit à partir de tes consignes : Prompt Maître Agent IA autonome, ORCHESTRA-IA, Équipe Full-Stack Zero Trust v2, Quant Validation Master Prompt, Rôle IA trading, Expert trading/minage et Assistant (mandat mentor).
> Illustratif, pas un conseil financier. Aucune garantie de performance.

---

## 0. Position du trader expert (à lire en premier)

**Ce que l'application garantit par conception :**

| Exigence | Comment c'est garanti | Garantie |
|---|---|---|
| **Pas de liquidation** | Marché **SPOT uniquement**, levier = 1, futures, marge et emprunt **interdits dans le code** (pas de simple réglage) | ✅ Totale. Sans levier, aucune liquidation n'est possible |
| **Pas de faillite** | Risque ≤ 1 % par trade, exposition ≤ 20 % par position, coupe-circuit à −3 %/jour et −10 % depuis le plus haut | ✅ Une ruine exigerait des centaines de pertes d'affilée, et le système s'arrête bien avant |
| **Pas de risque inutile** | Une stratégie ne touche l'argent réel qu'après **3 gates** de validation, puis le paper trading | ✅ Par processus |
| **Les fonds restent chez toi** | Clés API **sans droit de retrait**, whitelist d'IP | ✅ Même un piratage du serveur ne permet pas de retirer |

**Ce qu'aucune IA ne peut garantir :** qu'un trade ne perde jamais. Les meilleurs fonds perdent sur 40 à 50 % de leurs trades. Un trader qui « fait toujours du profit » gagne **sur la durée**, avec des pertes petites et des gains plus grands que ses pertes. L'IA est construite sur ce principe : **le capital d'abord, la performance ensuite.**

### Vérité sur les paliers 10 000 → 100 000 → 1 000 000 FCFA

Il faut multiplier le capital par 100. Voici les simulations en mois réguliers, ce qui est optimiste puisqu'il y aura des mois négatifs :

| Rendement net / mois | Sans apport | Avec **10 000 FCFA d'apport / mois** | Avec 25 000 FCFA / mois |
|---|---|---|---|
| 2 % (bon) | 100k : 9,8 ans · 1M : 19,4 ans | 100k : **10 mois** · 1M : **4,6 ans** | 1M : 2,5 ans |
| 3 % (excellent) | 100k : 6,5 ans · 1M : 13 ans | 100k : 8 mois · 1M : **3,8 ans** | 1M : 2,2 ans |
| 5 % (exceptionnel, rarement tenu) | 1M : 7,9 ans | 1M : 3 ans | 1M : 1,9 an |

**Conclusion d'expert :** au début, **c'est ton épargne régulière qui fait grossir le compte, pas le trading.** Le trading devient le moteur principal à partir d'environ 500 000 FCFA. Toute IA qui prétend aller plus vite avec 10 000 FCFA prend des risques qui mènent à la faillite. L'application intègre donc un **plan d'apport mensuel** (Mobile Money vers l'exchange) comme fonctionnalité centrale.

### Contrainte technique du petit capital (point bloquant à connaître)

Sur Binance, un ordre spot doit faire **au moins environ 5 USDT (≈ 3 000 FCFA)**. Avec 10 000 FCFA et la règle « 20 % max par position », une position fait 2 000 FCFA, ce qui est **en dessous du minimum**. D'où le palier 0 :

- **Palier 0 (moins de 50 000 FCFA) : pas de trading actif.** Accumulation DCA (BTC/ETH) plus paper trading de l'IA en parallèle. L'IA s'entraîne, ton capital grossit grâce aux apports, sans risque inutile.
- **Palier 1 (50 000 FCFA ou plus) :** trading actif en réel, avec un petit capital alloué.

---

## 1. Principe d'architecture n° 1 : le LLM ne passe JAMAIS d'ordre

C'est la règle qui protège ton argent. Je l'applique à partir de tes consignes : kill switch indépendant du modèle, moteur inviolable, Human-in-the-loop sur les transactions.

```
 ┌──────────────── CERVEAU (agents IA / LLM) ─────────────────┐
 │  Recherche, hypothèses, backtests, audit, statistiques,      │
 │  rapports. → Produit des STRATÉGIES VALIDÉES (fichiers).     │
 │  ❌ Aucun accès aux clés de l'exchange.                      │
 └──────────────────────────┬──────────────────────────────────┘
                            │ stratégie versionnée + rapport des 3 gates
                            ▼  (+ validation humaine dans l'app)
 ┌──────────────── MAINS (code déterministe) ─────────────────┐
 │  Moteur d'exécution (Freqtrade), règles fixes, testées.     │
 │  Applique la stratégie 24h/24 SEUL, dans les limites.       │
 └──────────────────────────┬──────────────────────────────────┘
                            ▼
 ┌──────────────── GARDIEN (code séparé) ─────────────────────┐
 │  Risk Guard + Kill Switch : processus indépendant, qui peut │
 │  TOUT stopper. Le cerveau et les mains ne peuvent pas le    │
 │  désactiver.                                                 │
 └─────────────────────────────────────────────────────────────┘
```

**« L'IA tourne seule » signifie :** les mains tradent seules 24h/24 et le gardien surveille seul. Le cerveau cherche et améliore seul. Tu n'interviens que pour **3 décisions** : mettre en réel une nouvelle stratégie, redémarrer après un kill switch et augmenter les limites de risque.

**Le téléphone n'est pas le serveur.** Un téléphone se met en veille, perd le réseau et se décharge. Le bot tourne sur un **VPS** (≈ 3 000 à 6 000 FCFA/mois). L'application mobile est la **tour de contrôle** : suivi, alertes, validations et bouton d'arrêt d'urgence.

---

## 2. L'équipe d'agents (fusion de tes consignes)

### 2.1 Équipe « Trading » (le cerveau, pipeline quant de tes consignes)

Ces agents travaillent **séquentiellement** (règle ORCHESTRA-IA). Chaque gate bloque la suite.

| # | Agent | Rôle | Sortie | Gate |
|---|---|---|---|---|
| T0 | **ORCHESTRATEUR** (Agent 00) | Pilote le pipeline, tient le `PROJECT_STATE`, compte **N essais** | Plan, état, journal | — |
| T1 | **HYPOTHESIS** | Propose un **mécanisme économique** et nomme la contrepartie perdante. Pas de code | Fiche stratégie | Rejet si la contrepartie n'est pas nommée |
| T2 | **CODE** | Backtest vectorisé, `shift(1)`, frais **et** slippage sur turnover, UTC | DataFrame position/gross/costs/net/equity | — |
| T3 | **CRITIC** (risk manager hostile) | Audit en 8 points avec citation des lignes. Une seule ligne suspecte suffit à rejeter | Verdict | **GATE 1** |
| T4 | **STATISTICIAN** | Deflated Sharpe Ratio sur les N essais réels | DSR > 0,95 ? | **GATE 2** |
| T5 | **WALK-FORWARD** | Train 180 j / test 60 j glissant, découpage par régime bull/bear/chop (MA200) | Résultats par fold, pire fold | **GATE 3** |
| T6 | **RISK / CRO** | Taille = Capital × risk% / \|Entrée − Stop\|, simulation de 10 à 15 pertes d'affilée, kill conditions | Paramètres de risque | — |
| T7 | **PAPER TRADER** | Simulation en temps réel ≥ 4 semaines sur données live | Écart backtest vs live | Promotion |
| T8 | **AUDITEUR FINAL** (Agent 20) | Relit tout sans supposer que les autres ont raison | REJECTED / PAPER-ONLY / PRODUCTION-ELIGIBLE | Avant validation humaine |

**Règles absolues reprises de tes consignes :**
- Un Sharpe annualisé supérieur à 2 sur du crypto daily = **fuite présumée** jusqu'à preuve du contraire.
- Les stratégies rejetées sont **conservées** dans le journal. On ne supprime jamais un mauvais essai.
- Rejeter 199 idées sur 200 est un **succès**.
- « PRODUCTION-ELIGIBLE » ne veut jamais dire « garanti rentable ».

### 2.2 Équipe « Construction » (Full-Stack Zero Trust v2)

| Agent | Rôle dans ce projet |
|---|---|
| **Atlas**, chef de projet | Découpage, priorités, synthèse |
| **Iris**, UI/UX | Écrans, Material Design 3, zéro dark pattern (pas de bouton « tout miser ») |
| **Zen**, mobile | Application Flutter (Android d'abord), biométrie, Keystore, certificate pinning |
| **Rho**, backend | API FastAPI, PostgreSQL, journal immuable |
| **Talos**, DevOps | VPS, Docker Compose, CI/CD, sauvegardes |
| **Cipher**, sécurité | OWASP / MASVS, secrets, clés sans retrait, 2FA |
| **Vera**, QA | Tests unitaires, intégration, E2E, non-régression, tests du kill switch |
| **Sage**, IA | Intégration des LLM, anti-prompt-injection (une news ou un tweet n'est **jamais** une instruction) |

---

## 3. Règles de risque (codées en dur et testées)

| Règle | Valeur | Modifiable ? |
|---|---|---|
| Type de marché | **Spot uniquement** | ❌ Jamais |
| Levier | **1** | ❌ Jamais |
| Risque par trade | **1 %** du capital (0,5 % au démarrage) | Seulement à la baisse sans validation |
| Stop-loss | **Obligatoire**, posé sur l'exchange à l'ouverture | ❌ |
| Exposition par position | ≤ 20 % du capital | Validation humaine |
| Exposition totale | ≤ 60 % (≥ 40 % toujours en USDT) | Validation humaine |
| Positions simultanées | ≤ 3, actifs non corrélés | Validation humaine |
| Moyenne à la baisse / martingale | **Interdite** | ❌ |
| Actifs autorisés | Top liquidité seulement (BTC, ETH, SOL, BNB…), filtres de spread et de volume | Validation humaine |
| **Coupe-circuit journalier** | −3 % → plus de nouvelles entrées jusqu'au lendemain | Automatique |
| **Kill switch** | DD > 10 %, ou DD > 1,5 × DD max du backtest, ou Sharpe live 30 j < 50 % du backtest | Redémarrage **manuel** obligatoire |
| Panne de données / exchange | Arrêt des entrées, positions protégées par leur stop | Automatique |
| Pertes consécutives | 4 d'affilée → risque divisé par 2 ; 6 → pause de 48 h | Automatique |

**Simulation du pire chemin** (règle CRO) : avec 1 % de risque et 15 pertes d'affilée, le drawdown est d'environ −14 %. Le kill switch coupe avant, à −10 %. Le compte survit.

---

## 4. Système de paliers (ton objectif 10k → 100k → 1M)

| Palier | Capital | Mode de l'IA | Sécurisation des gains |
|---|---|---|---|
| **P0** | 0 à 50 000 FCFA | DCA + **paper trading** de l'IA | — |
| **P1** | 50k à 100k | Réel, risque 0,5 %, 1 stratégie | — |
| **🎯 Objectif 1** | **100 000 FCFA** | Revalidation complète | 20 % des **gains** mis à l'abri |
| **P2** | 100k à 1M | Risque 1 %, jusqu'à 3 stratégies non corrélées | À chaque +100k : 20 % des gains à l'abri |
| **🎯 Objectif 2** | **1 000 000 FCFA** | Audit complet, nouveau plan | 25 % des gains à l'abri (portefeuille froid ou retrait) |
| **P3** | 1M à 10M | Diversification, réduction du risque relatif | Retraits réguliers possibles |

**Règle d'or :** l'argent mis à l'abri **ne retourne jamais** au trading. C'est ce qui rend la faillite impossible même dans le pire scénario. Si le compte recule sous un palier atteint, l'IA **réduit son risque** au lieu de « se refaire ».

---

## 5. L'application mobile (tour de contrôle)

**Technologie :** Flutter (Android d'abord, iOS ensuite avec le même code).
**Sécurité :** connexion biométrique, jeton dans le Keystore, certificate pinning, **aucune clé d'exchange dans le téléphone**.

### Écrans

1. **Accueil** : capital en FCFA (et USDT), barre de progression vers le prochain palier, P&L du jour/semaine/mois, drawdown actuel avec jauge colorée et statut du système (🟢 actif / 🟡 pause / 🔴 kill switch).
2. **Positions** : positions ouvertes, stop-loss, risque engagé en FCFA.
3. **Journal** : chaque trade avec la raison d'entrée, la sortie et le résultat. Export CSV.
4. **Agents** : pipeline en direct (Hypothesis → Critic → Stat → Walk-forward), stratégies en cours, rejetées et validées, compteur N d'essais.
5. **Validations** (Human-in-the-loop) : « Stratégie X a passé les 3 gates et 4 semaines de paper trading. Rapport complet. **[Approuver en réel avec 10 % du capital] [Refuser]** ». Approbation par biométrie et code à 2 chiffres.
6. **Risque** : limites actives, historique des coupe-circuits et le **gros bouton rouge d'arrêt d'urgence** (ferme les entrées, annule les ordres et, en option, vend tout en USDT).
7. **Apports** : plan d'apport mensuel, rappels et historique des dépôts Mobile Money vers l'exchange.
8. **Rapports** : rapport quotidien et hebdomadaire écrit par l'agent rédacteur, en français simple.
9. **Paramètres** : notifications, langue, sécurité, sessions actives.

### Notifications push
Trade ouvert ou fermé · coupe-circuit déclenché · stratégie en attente de validation · palier atteint 🎉 · anomalie (exchange injoignable, slippage anormal).

---

## 6. Architecture technique

```
[Téléphone Flutter] ──HTTPS + pinning──► [API FastAPI] ──► PostgreSQL (journal immuable)
                                             │
              ┌──────────────────────────────┼─────────────────────────────┐
              ▼                              ▼                             ▼
  [Agents IA — LangGraph]        [Exécution — Freqtrade]        [Risk Guard / Kill Switch]
  Claude API (Opus/Sonnet)        stratégie validée, spot       processus séparé, lit le
  backtests en sandbox Docker     clés sans retrait + IP fixe   compte en direct, peut tout
  N essais comptés                                               stopper
              │                              │                             │
              └────────────► Monitoring (Prometheus/Grafana) + alertes push/Telegram ◄┘

Hébergement : 1 VPS (Docker Compose), sauvegardes chiffrées quotidiennes
```

| Composant | Choix | Pourquoi |
|---|---|---|
| Exécution | **Freqtrade** (open source, mûr) | Stop-loss sur l'exchange, protections natives (StoplossGuard, MaxDrawdown, CooldownPeriod), dry-run intégré |
| Orchestration des agents | **LangGraph** | Graphe d'états, pause/reprise, Human-in-the-loop, traçabilité |
| LLM | Claude API | Raisonnement des agents (jamais d'exécution d'ordres) |
| Backtest | Moteur vectorisé Pandas « inviolable » de tes consignes, versionné et testé | Anti-fuite |
| Exchange | Binance spot (à confirmer) | Liquidité, P2P en FCFA via Mobile Money |
| Mobile | Flutter | Android et iOS avec un seul code |

---

## 7. Feuille de route (évolution progressive, Niveaux 1 → 7 de tes consignes)

| Phase | Contenu | Durée indicative | Critère pour passer à la suite |
|---|---|---|---|
| **1. Fondations** | Moteur de backtest et ses tests, Risk Guard, API, base de données | 2 à 3 semaines | Tests à 100 %, kill switch testé |
| **2. Cerveau** | Pipeline des agents T1→T8, première stratégie candidate | 2 à 3 semaines | Une stratégie passe les 3 gates (ou rapport honnête si aucune ne passe) |
| **3. Application** | Écrans Flutter 1 à 9, notifications, biométrie | 3 semaines | Tests E2E et audit sécurité MASVS |
| **4. Paper trading** | Bot en dry-run sur le VPS, suivi depuis l'app | **≥ 4 semaines** | Écart live/backtest acceptable, aucun incident |
| **5. Réel minimal** | Petit capital réel (≤ 5 % de l'épargne totale) | 4 à 8 semaines | Kill conditions jamais déclenchées |
| **6. Croissance** | Paliers, ajout de stratégies non corrélées | Continu | Revue mensuelle |

---

## 8. Ce que l'IA ne fera JAMAIS (veto du mentor)

- ❌ Futures, marge, levier ou « x10 pour aller plus vite »
- ❌ Martingale ou doublement après une perte
- ❌ Trader sans stop-loss
- ❌ Désactiver le kill switch « juste cette fois »
- ❌ Suivre un signal Telegram, un influenceur ou une news non vérifiée
- ❌ Utiliser l'argent mis à l'abri ou emprunter pour trader
- ❌ Promettre un rendement

---

## 9. Décisions validées (16/10/2026)

| Décision | Choix |
|---|---|
| Marché | **Crypto spot sur Binance** |
| Capital de départ | **20 000 FCFA** |
| Apport mensuel | **20 000 FCFA** |
| Téléphone | **Android seul** (v1, Flutter) |
| Hébergement | VPS et API Claude acceptés |

### Projection avec ce plan (20 000 + 20 000 FCFA/mois, rendement constant illustratif)

| Rendement net / mois | 50 000 FCFA (palier P1) | 100 000 FCFA | 1 000 000 FCFA |
|---|---|---|---|
| 0 % (épargne seule) | 2 mois | 4 mois | 49 mois (≈ 4 ans) |
| 1 % | 2 mois | 4 mois | 40 mois |
| 2 % | 2 mois | 4 mois | 35 mois (≈ 3 ans) |
| 3 % | 2 mois | 4 mois | 30 mois (2,5 ans) |

**Lecture du trader :** la discipline d'apport te garantit le million en environ 4 ans **sans aucun risque**. Le rôle de l'IA est de **raccourcir** ce délai d'un an environ, **jamais de le mettre en danger**. Une IA qui perd est pire que pas d'IA. C'est pourquoi le gardien a le dernier mot.

Calendrier : construction + paper trading ≈ 3 mois. Pendant ce temps, tes apports font passer le compte en P1, puis vers 100 000 FCFA. L'IA démarrera donc en réel avec un capital qui permet de respecter les minimums de Binance.

### Avancement
- ✅ **Phase 1 livrée** (`/home/user/sentinelle`) : moteur anti-fuite, gates 1-2-3, dimensionnement, gardien et kill switch, paliers. **54 tests passent.**
- ⏭️ Phase 2 : pipeline d'agents (LangGraph + Claude) et stratégie Freqtrade en dry-run.
- ⏭️ Phase 3 : application Android Flutter.
