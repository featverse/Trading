"""Génère le hash du mot de passe de l'opérateur et des secrets aléatoires.

Usage : python scripts/hash_password.py
Copie les lignes affichées dans deploy/.env (jamais dans Git).
"""

import getpass
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sentinelle.api.security import hash_password  # noqa: E402

pw = getpass.getpass("Mot de passe de l'application (12 caractères minimum) : ")
if pw != getpass.getpass("Confirme : "):
    raise SystemExit("Les mots de passe ne correspondent pas.")
print(f"SENTINELLE_PASSWORD_HASH={hash_password(pw)}")
print(f"SENTINELLE_TOKEN_SECRET={secrets.token_hex(32)}")
print(f"SENTINELLE_INTERNAL_TOKEN={secrets.token_hex(32)}")
