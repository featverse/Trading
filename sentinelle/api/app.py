"""API de SENTINELLE — la « tour de contrôle » que l'application Android interroge.

Lancer : uvicorn sentinelle.api.app:app --host 127.0.0.1 --port 8000
(exposée à Internet uniquement derrière un reverse proxy HTTPS, voir deploy/).
"""

from __future__ import annotations

import json
import re
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from sentinelle.api.freqtrade_client import FreqtradeAPI, FreqtradeClient, FreqtradeError
from sentinelle.api.security import LoginThrottle, TokenError, issue_token, read_token, verify_password
from sentinelle.api.settings import Settings
from sentinelle.api.store import Store
from sentinelle.api.supervisor import Supervisor
from sentinelle.config import RiskLimits
from sentinelle.risk.guard import RESET_CONFIRMATION
from sentinelle.risk.tiers import project_months_to_target

NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{2,40}$")
MAX_FIRST_ALLOCATION = 0.10  # 10 % du capital pour une première mise en réel
DISCLAIMER = "Illustratif, pas un conseil financier. Aucune garantie de performance."


# --- Schémas -------------------------------------------------------------------------
class LoginIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class RefreshIn(BaseModel):
    refresh_token: str


class StepUpIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)
    confirmation: str


class ApproveIn(StepUpIn):
    capital_pct: float = Field(gt=0, le=MAX_FIRST_ALLOCATION)


class EmergencyIn(BaseModel):
    exit_all: bool = False


class DepositIn(BaseModel):
    amount_fcfa: float = Field(gt=0, le=10_000_000)
    note: str = Field(default="Mobile Money", max_length=120)


class EntryCheckIn(BaseModel):
    pair: str
    rate: float = Field(gt=0)
    stop_rate: float = Field(gt=0)
    notional: float = Field(gt=0)


# --- Application -----------------------------------------------------------------------
def create_app(
    settings: Settings,
    freqtrade: FreqtradeAPI | None = None,
    store: Store | None = None,
    run_supervisor: bool = True,
    tick_seconds: int = 60,
) -> FastAPI:
    store = store or Store(settings.db_path)
    freqtrade = freqtrade or FreqtradeClient(settings.freqtrade_url, settings.freqtrade_username, settings.freqtrade_password)
    supervisor = Supervisor(settings, store, freqtrade)
    throttle = LoginThrottle()
    stop_flag = threading.Event()

    def loop() -> None:
        while not stop_flag.is_set():
            try:
                supervisor.tick()
            except Exception as exc:  # le superviseur ne doit jamais mourir silencieusement
                store.event("SUPERVISOR_ERROR", repr(exc))
            stop_flag.wait(tick_seconds)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        thread = threading.Thread(target=loop, daemon=True) if run_supervisor else None
        if thread:
            thread.start()
        yield
        stop_flag.set()

    app = FastAPI(title="SENTINELLE", version="0.3.0", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.supervisor = supervisor
    app.state.store = store

    # --- Authentification ----------------------------------------------------------
    def operator(authorization: Annotated[str | None, Header()] = None) -> dict:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Authentification requise.")
        try:
            return read_token(settings.token_secret, authorization.removeprefix("Bearer "), "access")
        except TokenError as exc:
            raise HTTPException(401, str(exc)) from exc

    def step_up(body: StepUpIn, expected_confirmation: str) -> None:
        now = time.time()
        try:
            throttle.check(now)
        except TokenError as exc:
            raise HTTPException(429, str(exc)) from exc
        if not verify_password(body.password, settings.password_hash):
            throttle.fail(now)
            raise HTTPException(403, "Mot de passe incorrect.")
        throttle.success()
        if body.confirmation.strip() != expected_confirmation:
            raise HTTPException(400, f"Tape exactement : {expected_confirmation}")

    def tokens() -> dict:
        refresh = issue_token(settings.token_secret, "refresh", settings.refresh_ttl_seconds)
        store.register_refresh(read_token(settings.token_secret, refresh, "refresh")["jti"])
        return {
            "access_token": issue_token(settings.token_secret, "access", settings.access_ttl_seconds),
            "refresh_token": refresh,
            "expires_in": settings.access_ttl_seconds,
        }

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.post("/auth/login")
    def login(body: LoginIn, request: Request) -> dict:
        now = time.time()
        try:
            throttle.check(now)
        except TokenError as exc:
            raise HTTPException(429, str(exc)) from exc
        if not verify_password(body.password, settings.password_hash):
            throttle.fail(now)
            store.event("LOGIN_FAILED", f"Échec de connexion depuis {request.client.host if request.client else '?'}")
            raise HTTPException(401, "Mot de passe incorrect.")
        throttle.success()
        store.event("LOGIN", "Connexion de l'opérateur.")
        return tokens()

    @app.post("/auth/refresh")
    def refresh(body: RefreshIn) -> dict:
        try:
            payload = read_token(settings.token_secret, body.refresh_token, "refresh")
        except TokenError as exc:
            raise HTTPException(401, str(exc)) from exc
        if not store.refresh_valid(payload["jti"]):
            raise HTTPException(401, "Session révoquée.")
        store.revoke_refresh(payload["jti"])  # rotation : un jeton de rafraîchissement ne sert qu'une fois
        return tokens()

    @app.post("/auth/logout-all")
    def logout_all(_: dict = Depends(operator)) -> dict:
        store.revoke_refresh()
        store.event("LOGOUT_ALL", "Toutes les sessions ont été révoquées.")
        return {"ok": True}

    # --- Tableau de bord --------------------------------------------------------------
    @app.get("/status")
    def status(_: dict = Depends(operator)) -> dict:
        snap = supervisor.snapshot()
        cap = snap["equity_fcfa"] or settings.initial_capital_fcfa
        monthly = settings.monthly_deposit_fcfa
        snap["plan"] = {
            "monthly_deposit_fcfa": monthly,
            "months_to_100k": {f"{int(r * 100)}%": project_months_to_target(cap, monthly, r, 100_000) for r in (0.0, 0.02)},
            "months_to_1m": {f"{int(r * 100)}%": project_months_to_target(cap, monthly, r, 1_000_000) for r in (0.0, 0.02)},
        }
        snap["disclaimer"] = DISCLAIMER
        return snap

    @app.get("/trades")
    def trades(_: dict = Depends(operator)) -> dict:
        try:
            return {"open": freqtrade.open_trades(), "closed": freqtrade.closed_trades(limit=50), "error": None}
        except FreqtradeError as exc:
            return {"open": [], "closed": [], "error": str(exc)}

    @app.get("/events")
    def events(limit: int = 100, _: dict = Depends(operator)) -> list[dict]:
        return store.events(min(max(limit, 1), 500))

    # --- Stratégies ---------------------------------------------------------------------
    def strategy_dir(name: str) -> Path:
        if not NAME_RE.match(name):
            raise HTTPException(400, "Nom de stratégie invalide.")
        path = Path(settings.research_dir) / "strategies" / name
        if not (path / "dossier.json").is_file():
            raise HTTPException(404, "Stratégie inconnue.")
        return path

    def summary(path: Path) -> dict:
        dossier = json.loads((path / "dossier.json").read_text(encoding="utf-8"))
        name = path.name
        started = store.paper_started(name)
        days = (datetime.now(timezone.utc) - started).days if started else 0
        return {
            "name": name,
            "decision": dossier.get("decision"),
            "reason": dossier.get("reason"),
            "gates": dossier.get("gates", {}),
            "asset": dossier.get("spec", {}).get("asset"),
            "timeframe": dossier.get("spec", {}).get("timeframe"),
            "paper_started_at": started.isoformat() if started else None,
            "paper_days": days,
            "approval": store.approval(name),
        }

    @app.get("/strategies")
    def strategies(_: dict = Depends(operator)) -> list[dict]:
        root = Path(settings.research_dir) / "strategies"
        if not root.is_dir():
            return []
        return [summary(p) for p in sorted(root.iterdir()) if (p / "dossier.json").is_file() and NAME_RE.match(p.name)]

    @app.get("/strategies/{name}")
    def strategy(name: str, _: dict = Depends(operator)) -> dict:
        path = strategy_dir(name)
        report = path / "rapport.md"
        return {**summary(path), "report_md": report.read_text(encoding="utf-8") if report.is_file() else ""}

    @app.post("/strategies/{name}/paper/start")
    def paper_start(name: str, _: dict = Depends(operator)) -> dict:
        info = summary(strategy_dir(name))
        if info["decision"] != "PAPER_TRADING_ONLY":
            raise HTTPException(409, "Seule une stratégie validée par les 3 gates peut passer en simulation.")
        store.start_paper(name)
        store.event("PAPER_START", f"Simulation démarrée pour {name}.")
        return summary(strategy_dir(name))

    @app.post("/strategies/{name}/approve")
    def approve(name: str, body: ApproveIn, _: dict = Depends(operator)) -> dict:
        info = summary(strategy_dir(name))
        if info["decision"] != "PAPER_TRADING_ONLY":
            raise HTTPException(409, "Stratégie non validée par les 3 gates.")
        if info["paper_days"] < settings.min_paper_days:
            raise HTTPException(409, f"Simulation de {info['paper_days']} jours : il en faut au moins {settings.min_paper_days}.")
        snap = supervisor.snapshot()
        if snap["status"] != "ACTIVE":
            raise HTTPException(409, f"Gardien en statut {snap['status']} : approbation impossible.")
        if not snap["tier"]["live_trading"]:
            raise HTTPException(409, f"Palier {snap['tier']['name']} : capital encore trop petit pour trader en réel.")
        step_up(body, f"J'APPROUVE {name}")
        store.approve(name, body.capital_pct)
        store.event("APPROVED_LIVE", f"{name} approuvée pour le réel avec {body.capital_pct:.0%} du capital.")
        return {
            **summary(strategy_dir(name)),
            "next_steps": [
                "Créer la clé API Binance : lecture + trading spot, RETRAIT DÉSACTIVÉ, IP du VPS en liste blanche.",
                "Mettre la clé dans deploy/.env (jamais dans Git), passer dry_run à false, redémarrer le bot.",
                "Le gardien reste actif : coupe-circuit -3 %/jour, arrêt à -10 %.",
            ],
        }

    # --- Risque -------------------------------------------------------------------------------
    @app.get("/risk")
    def risk(_: dict = Depends(operator)) -> dict:
        limits = RiskLimits()
        guard = supervisor.guard
        return {
            "limits": {
                "spot_only": True,
                "max_leverage": 1,
                "risk_per_trade": limits.risk_per_trade,
                "max_position_pct": limits.max_position_pct,
                "max_total_exposure": limits.max_total_exposure,
                "daily_loss_limit": limits.daily_loss_limit,
                "max_drawdown": limits.max_drawdown,
                "max_positions": limits.max_positions,
            },
            "status": supervisor.snapshot()["status"],
            "guard_events": (guard.state.events[-50:] if guard else [])[::-1],
            "reset_confirmation": RESET_CONFIRMATION,
        }

    @app.post("/risk/emergency-stop")
    def emergency_stop(body: EmergencyIn, _: dict = Depends(operator)) -> dict:
        # Arrêter va toujours dans le sens de la sécurité : pas de mot de passe demandé.
        return {"status": "HALTED", "notes": supervisor.emergency_stop(body.exit_all)}

    @app.post("/risk/reset")
    def reset(body: StepUpIn, _: dict = Depends(operator)) -> dict:
        step_up(body, RESET_CONFIRMATION)
        if not supervisor.reset(body.confirmation):
            raise HTTPException(409, "Le système n'est pas en arrêt (HALTED).")
        return {"status": "ACTIVE"}

    # --- Plan d'épargne -------------------------------------------------------------------------
    @app.get("/deposits")
    def deposits(_: dict = Depends(operator)) -> list[dict]:
        return store.deposits()

    @app.post("/deposits")
    def add_deposit(body: DepositIn, _: dict = Depends(operator)) -> dict:
        supervisor.log_planned_deposit(body.amount_fcfa, body.note)
        return {"ok": True}

    # --- Interne : le bot demande l'autorisation avant chaque entrée -------------------
    @app.post("/internal/guard/check")
    def internal_check(body: EntryCheckIn, x_internal_token: Annotated[str | None, Header()] = None) -> dict:
        import hmac

        if not x_internal_token or not hmac.compare_digest(x_internal_token, settings.internal_token):
            raise HTTPException(401, "Jeton interne invalide.")
        decision = supervisor.check_entry(body.pair, body.rate, body.stop_rate, body.notional)
        return {"approved": decision.approved, "reasons": list(decision.reasons)}

    return app


def _app_from_env() -> FastAPI:
    return create_app(Settings.from_env())


def __getattr__(name: str):  # `uvicorn sentinelle.api.app:app` construit l'app à la demande
    if name == "app":
        return _app_from_env()
    raise AttributeError(name)
