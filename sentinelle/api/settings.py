"""Configuration du serveur — lue depuis l'environnement, jamais depuis Git."""

from __future__ import annotations

import os
from dataclasses import dataclass


class SettingsError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    password_hash: str  # généré par scripts/hash_password.py
    token_secret: str  # >= 32 caractères aléatoires
    internal_token: str  # partagé avec le bot Freqtrade (contrôle des entrées)
    db_path: str = "sentinelle.sqlite"
    research_dir: str = "research"
    freqtrade_url: str = "http://freqtrade:8080"
    freqtrade_username: str = "sentinelle"
    freqtrade_password: str = ""
    usdt_to_fcfa: float = 600.0  # À VÉRIFIER / mettre à jour : taux indicatif
    initial_capital_fcfa: float = 20_000.0
    monthly_deposit_fcfa: float = 20_000.0
    access_ttl_seconds: int = 15 * 60
    refresh_ttl_seconds: int = 30 * 24 * 3600
    min_paper_days: int = 28

    def __post_init__(self) -> None:
        if len(self.token_secret) < 32 or len(self.internal_token) < 32:
            raise SettingsError("SENTINELLE_TOKEN_SECRET et SENTINELLE_INTERNAL_TOKEN : 32 caractères minimum.")
        if not self.password_hash.startswith("scrypt$"):
            raise SettingsError("SENTINELLE_PASSWORD_HASH invalide (utiliser scripts/hash_password.py).")
        if self.usdt_to_fcfa <= 0:
            raise SettingsError("Taux USDT→FCFA invalide.")

    @classmethod
    def from_env(cls) -> "Settings":
        def req(name: str) -> str:
            value = os.environ.get(name, "")
            if not value:
                raise SettingsError(f"Variable d'environnement manquante : {name}")
            return value

        return cls(
            password_hash=req("SENTINELLE_PASSWORD_HASH"),
            token_secret=req("SENTINELLE_TOKEN_SECRET"),
            internal_token=req("SENTINELLE_INTERNAL_TOKEN"),
            db_path=os.environ.get("SENTINELLE_DB", "sentinelle.sqlite"),
            research_dir=os.environ.get("SENTINELLE_RESEARCH_DIR", "research"),
            freqtrade_url=os.environ.get("SENTINELLE_FREQTRADE_URL", "http://freqtrade:8080"),
            freqtrade_username=os.environ.get("SENTINELLE_FREQTRADE_USER", "sentinelle"),
            freqtrade_password=os.environ.get("FREQTRADE__API_SERVER__PASSWORD", ""),
            usdt_to_fcfa=float(os.environ.get("SENTINELLE_USDT_FCFA", "600")),
            initial_capital_fcfa=float(os.environ.get("SENTINELLE_INITIAL_FCFA", "20000")),
            monthly_deposit_fcfa=float(os.environ.get("SENTINELLE_MONTHLY_FCFA", "20000")),
        )
