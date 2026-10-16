import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from sentinelle.api.app import create_app
from sentinelle.api.freqtrade_client import FreqtradeError
from sentinelle.api.security import hash_password, issue_token, read_token, TokenError, verify_password
from sentinelle.api.settings import Settings, SettingsError
from sentinelle.api.store import Store
from sentinelle.risk.guard import RESET_CONFIRMATION

PASSWORD = "mot-de-passe-solide-123"
HASH = hash_password(PASSWORD)
T0 = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)


class FakeFreqtrade:
    def __init__(self, balance=100.0, profit=0.0):
        self.balance, self.profit = balance, profit
        self.opens, self.closed = [], []
        self.down = False
        self.stopped = self.exited = 0

    def _check(self):
        if self.down:
            raise FreqtradeError("injoignable")

    def balance_usdt(self):
        self._check()
        return self.balance

    def profit_total_usdt(self):
        self._check()
        return self.profit

    def open_trades(self):
        self._check()
        return self.opens

    def closed_trades(self, limit=50):
        self._check()
        return self.closed

    def stop_entries(self):
        self._check()
        self.stopped += 1

    def exit_all(self):
        self._check()
        self.exited += 1


@pytest.fixture
def env(tmp_path):
    settings = Settings(
        password_hash=HASH,
        token_secret="s" * 40,
        internal_token="i" * 40,
        db_path=str(tmp_path / "db.sqlite"),
        research_dir=str(tmp_path / "research"),
        usdt_to_fcfa=600.0,
    )
    ft = FakeFreqtrade()
    app = create_app(settings, freqtrade=ft, store=Store(settings.db_path), run_supervisor=False)
    client = TestClient(app)
    return settings, ft, app, client


def login(client):
    r = client.post("/auth/login", json={"password": PASSWORD})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, r.json()


def write_strategy(settings, name="trend_ok", decision="PAPER_TRADING_ONLY"):
    d = __import__("pathlib").Path(settings.research_dir) / "strategies" / name
    d.mkdir(parents=True)
    (d / "dossier.json").write_text(json.dumps({"decision": decision, "reason": "r", "gates": {"gate1": "PASS"},
                                                "spec": {"asset": "BTC/USDT", "timeframe": "1d"}}))
    (d / "rapport.md").write_text("# Rapport\n")
    return name


# --- Sécurité ---------------------------------------------------------------------
def test_password_hash_roundtrip():
    assert verify_password(PASSWORD, HASH)
    assert not verify_password("mauvais", HASH)
    with pytest.raises(ValueError):
        hash_password("court")


def test_tokens_signature_kind_and_expiry():
    tok = issue_token("k" * 40, "access", 60, now=1000)
    assert read_token("k" * 40, tok, "access", now=1030)["sub"] == "operator"
    with pytest.raises(TokenError):
        read_token("k" * 40, tok, "access", now=2000)
    with pytest.raises(TokenError):
        read_token("k" * 40, tok, "refresh", now=1030)
    with pytest.raises(TokenError):
        read_token("autre" * 10, tok, "access", now=1030)


def test_settings_reject_weak_secrets():
    with pytest.raises(SettingsError):
        Settings(password_hash=HASH, token_secret="court", internal_token="i" * 40)


def test_endpoints_require_auth(env):
    _, _, _, client = env
    assert client.get("/health").status_code == 200
    for path in ("/status", "/trades", "/strategies", "/risk", "/events", "/deposits"):
        assert client.get(path).status_code == 401
    assert client.get("/status", headers={"Authorization": "Bearer faux.jeton"}).status_code == 401


def test_login_lockout_after_five_failures(env):
    _, _, _, client = env
    for _ in range(5):
        assert client.post("/auth/login", json={"password": "faux"}).status_code == 401
    assert client.post("/auth/login", json={"password": PASSWORD}).status_code == 429


def test_refresh_rotation_and_revocation(env):
    _, _, _, client = env
    headers, toks = login(client)
    r = client.post("/auth/refresh", json={"refresh_token": toks["refresh_token"]})
    assert r.status_code == 200
    # Un jeton de rafraîchissement ne sert qu'une fois.
    assert client.post("/auth/refresh", json={"refresh_token": toks["refresh_token"]}).status_code == 401
    client.post("/auth/logout-all", headers=headers)
    assert client.post("/auth/refresh", json={"refresh_token": r.json()["refresh_token"]}).status_code == 401


# --- Superviseur -------------------------------------------------------------------
def test_status_after_tick(env):
    _, ft, app, client = env
    headers, _ = login(client)
    app.state.supervisor.tick(T0)
    s = client.get("/status", headers=headers).json()
    assert s["status"] == "ACTIVE"
    assert s["equity_fcfa"] == pytest.approx(60_000)
    assert s["tier"]["name"] == "P1"
    assert "Aucune garantie" in s["disclaimer"]


def test_drawdown_halts_and_stops_bot(env):
    _, ft, app, client = env
    sup = app.state.supervisor
    sup.tick(T0)
    ft.balance, ft.profit = 89.0, -11.0  # vraie perte de trading : -11 %
    sup.tick(T0 + timedelta(days=1))
    assert sup.snapshot()["status"] == "HALTED"
    assert ft.stopped == 1


def test_deposit_and_withdrawal_are_not_gains_or_losses(env):
    _, ft, app, _ = env
    sup = app.state.supervisor
    sup.tick(T0)
    ft.balance = 133.0  # apport de 33 USDT, profit inchangé
    sup.tick(T0 + timedelta(minutes=1))
    ft.balance = 90.0  # retrait (mise à l'abri) de 43 USDT : NE DOIT PAS déclencher de HALT
    sup.tick(T0 + timedelta(minutes=2))
    assert sup.snapshot()["status"] == "ACTIVE"
    kinds = [e["kind"] for e in app.state.store.events()]
    assert "DEPOSIT_DETECTED" in kinds and "WITHDRAWAL_DETECTED" in kinds
    ft.balance, ft.profit = 80.0, -10.0  # puis une vraie perte de 11 %
    sup.tick(T0 + timedelta(days=1))
    assert sup.snapshot()["status"] == "HALTED"


def test_bot_unreachable_blocks_entries(env):
    settings, ft, app, client = env
    sup = app.state.supervisor
    sup.tick(T0)
    body = {"pair": "BTC/USDT", "rate": 100.0, "stop_rate": 95.0, "notional": 15.0}
    hdr = {"X-Internal-Token": settings.internal_token}
    # Données vieilles de plus de 3 minutes : refus.
    ft.down = True
    for i in range(3):
        sup.tick(T0 + timedelta(minutes=i + 1))
    r = client.post("/internal/guard/check", json=body, headers=hdr).json()
    assert r["approved"] is False


def test_internal_check_token_and_rules(env):
    settings, ft, app, client = env
    now = datetime.now(timezone.utc)
    app.state.supervisor.tick(now)
    # Risque : 9 USDT × ~5,2 % ≈ 0,47 USDT ≤ 0,5 % de 100 USDT (limite de démarrage).
    body = {"pair": "BTC/USDT", "rate": 100.0, "stop_rate": 95.0, "notional": 9.0}
    assert client.post("/internal/guard/check", json=body).status_code == 401
    assert client.post("/internal/guard/check", json=body, headers={"X-Internal-Token": "x" * 40}).status_code == 401
    hdr = {"X-Internal-Token": settings.internal_token}
    assert client.post("/internal/guard/check", json=body, headers=hdr).json()["approved"] is True
    big = {**body, "notional": 50.0}  # 50 % du capital > 20 %
    assert client.post("/internal/guard/check", json=big, headers=hdr).json()["approved"] is False
    risky = {**body, "notional": 15.0}  # 0,78 USDT de risque > 0,50 autorisé
    r = client.post("/internal/guard/check", json=risky, headers=hdr).json()
    assert r["approved"] is False and any("Risque" in x for x in r["reasons"])


def test_emergency_stop_then_reset_with_step_up(env):
    _, ft, app, client = env
    headers, _ = login(client)
    app.state.supervisor.tick(T0)
    r = client.post("/risk/emergency-stop", json={"exit_all": True}, headers=headers).json()
    assert r["status"] == "HALTED" and ft.stopped == 1 and ft.exited == 1
    bad = client.post("/risk/reset", json={"password": "faux", "confirmation": RESET_CONFIRMATION}, headers=headers)
    assert bad.status_code == 403
    wrong_phrase = client.post("/risk/reset", json={"password": PASSWORD, "confirmation": "ok"}, headers=headers)
    assert wrong_phrase.status_code == 400
    ok = client.post("/risk/reset", json={"password": PASSWORD, "confirmation": RESET_CONFIRMATION}, headers=headers)
    assert ok.status_code == 200 and ok.json()["status"] == "ACTIVE"


def test_emergency_stop_reports_bot_failure(env):
    _, ft, app, client = env
    headers, _ = login(client)
    ft.down = True
    r = client.post("/risk/emergency-stop", json={"exit_all": False}, headers=headers).json()
    assert r["status"] == "HALTED"
    assert any("Vérifier sur Binance" in n for n in r["notes"])


# --- Stratégies --------------------------------------------------------------------------
def test_strategy_listing_and_path_traversal(env):
    settings, _, _, client = env
    headers, _ = login(client)
    write_strategy(settings)
    assert [s["name"] for s in client.get("/strategies", headers=headers).json()] == ["trend_ok"]
    assert client.get("/strategies/trend_ok", headers=headers).json()["report_md"].startswith("# Rapport")
    assert client.get("/strategies/..%2F..%2Fetc", headers=headers).status_code in (400, 404)


def test_rejected_strategy_cannot_go_to_paper(env):
    settings, _, _, client = env
    headers, _ = login(client)
    write_strategy(settings, "mauvaise", decision="REJECTED")
    assert client.post("/strategies/mauvaise/paper/start", headers=headers).status_code == 409


def test_approval_requires_28_days_tier_and_step_up(env):
    settings, ft, app, client = env
    headers, _ = login(client)
    name = write_strategy(settings)
    app.state.supervisor.tick(T0)
    client.post(f"/strategies/{name}/paper/start", headers=headers)
    body = {"password": PASSWORD, "confirmation": f"J'APPROUVE {name}", "capital_pct": 0.10}
    r = client.post(f"/strategies/{name}/approve", json=body, headers=headers)
    assert r.status_code == 409 and "28" in r.json()["detail"]
    # Simulation commencée il y a 30 jours.
    app.state.store._exec("UPDATE paper_runs SET started_at=?", ((datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),))
    too_much = client.post(f"/strategies/{name}/approve", json={**body, "capital_pct": 0.5}, headers=headers)
    assert too_much.status_code == 422
    r = client.post(f"/strategies/{name}/approve", json=body, headers=headers)
    assert r.status_code == 200, r.json()
    assert any("RETRAIT DÉSACTIVÉ" in s for s in r.json()["next_steps"])


def test_approval_refused_when_capital_too_small(env):
    settings, ft, app, client = env
    headers, _ = login(client)
    ft.balance = 33.0  # ≈ 20 000 FCFA : palier P0
    name = write_strategy(settings)
    app.state.supervisor.tick(T0)
    client.post(f"/strategies/{name}/paper/start", headers=headers)
    app.state.store._exec("UPDATE paper_runs SET started_at=?", ((datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),))
    body = {"password": PASSWORD, "confirmation": f"J'APPROUVE {name}", "capital_pct": 0.10}
    r = client.post(f"/strategies/{name}/approve", json=body, headers=headers)
    assert r.status_code == 409 and "P0" in r.json()["detail"]


def test_deposit_log_does_not_touch_guard(env):
    _, ft, app, client = env
    headers, _ = login(client)
    app.state.supervisor.tick(T0)
    peak = app.state.supervisor.guard.state.equity_peak
    assert client.post("/deposits", json={"amount_fcfa": 20000}, headers=headers).status_code == 200
    assert app.state.supervisor.guard.state.equity_peak == peak
    assert client.get("/deposits", headers=headers).json()[0]["amount_fcfa"] == 20000
