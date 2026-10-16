# Installation de SENTINELLE (VPS + téléphone Android)

> Durée : environ 1 h la première fois. Aucune clé Binance n'est nécessaire pendant la simulation.
> Illustratif, pas un conseil financier. Aucune garantie de performance.

## 1. Le serveur (VPS)

1. Loue un VPS Linux (Ubuntu 24.04, 2 Go de RAM suffisent, ≈ 3 000 à 6 000 FCFA/mois).
   Choisis une région hors des États-Unis : Binance n'y est pas accessible.
2. Connexion SSH **par clé** (pas par mot de passe), puis :
   ```bash
   sudo apt update && sudo apt install -y docker.io docker-compose-v2 git python3-venv ufw
   sudo ufw allow OpenSSH && sudo ufw allow 80 && sudo ufw allow 443 && sudo ufw enable
   git clone https://github.com/featverse/Trading.git && cd Trading
   ```
3. Un nom de domaine gratuit pour le HTTPS : crée un sous-domaine sur **duckdns.org**
   (ex. `monbot.duckdns.org`) pointant vers l'IP du VPS.

## 2. Les secrets

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/python scripts/hash_password.py      # choisis un mot de passe de 12+ caractères
cp deploy/.env.example deploy/.env && chmod 600 deploy/.env
nano deploy/.env   # colle les 3 lignes générées, SENTINELLE_DOMAIN, ANTHROPIC_API_KEY,
                   # et un mot de passe Freqtrade : openssl rand -hex 24
```
`deploy/.env` ne doit **jamais** être envoyé sur GitHub (il est déjà dans `.gitignore`).

## 3. Lancer la recherche des agents

```bash
set -a; . deploy/.env; set +a
.venv/bin/python scripts/run_research.py --ideas 3
```
Lis les rapports dans `research/strategies/*/rapport.md`. La plupart seront **rejetées** : c'est normal.

## 4. Démarrer le bot en simulation (seulement si une stratégie est validée)

```bash
NOM=<nom_de_la_strategie_validee>
cp research/strategies/$NOM/freqtrade/*.py deploy/user_data/strategies/
cp research/strategies/$NOM/freqtrade/config.dryrun.json deploy/user_data/config.json
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml logs -f --tail 50
```
Vérifie : `https://<ton-domaine>/health` doit répondre `{"ok":true}`.

Sans stratégie validée, ne lance pas le bot : relance la recherche plus tard.

## 5. L'application Android

1. Sur GitHub : onglet **Actions** → dernier passage vert de **CI** → artefact **sentinelle-android-apk**.
2. Télécharge et décompresse le zip, ouvre `app-release.apk` (autorise l'installation depuis cette source).
3. Ouvre **Sentinelle**, saisis `https://<ton-domaine>` et ton mot de passe.
4. Ensuite, l'application s'ouvre avec ton empreinte.

Dans l'application : démarre la simulation de la stratégie (onglet **Agents**). L'approbation pour
l'argent réel n'est possible qu'après **28 jours** de simulation, au palier P1 ou plus, avec ton mot
de passe et une phrase de confirmation.

## 6. Passage en réel (plus tard, jamais avant l'approbation dans l'application)

1. Binance → Gestion des API → clé avec **lecture + trading spot uniquement**, **retrait désactivé**,
   **restriction IP = IP du VPS**.
2. Mets la clé dans `deploy/.env` (`FREQTRADE__EXCHANGE__KEY` / `SECRET`).
3. Dans `deploy/user_data/config.json` : `"dry_run": false`. Redémarre : `docker compose ... up -d`.
4. Le gardien reste actif : −3 %/jour → pause, −10 % → arrêt total avec redémarrage manuel.

## En cas de problème

- **Bouton ARRÊT D'URGENCE** dans l'onglet Risque.
- Si le serveur ne répond plus : le bot refuse automatiquement toute nouvelle entrée.
- Téléphone perdu : depuis un autre appareil, « Déconnecter tous les appareils », puis change le
  mot de passe (`scripts/hash_password.py` puis redémarrage du serveur).
