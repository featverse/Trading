"""Persistance locale (SQLite, stdlib) : état du gardien, apports, validations,
dry-runs, événements, jetons révoqués."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT, kind TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS deposits (id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT, amount_fcfa REAL, note TEXT);
CREATE TABLE IF NOT EXISTS paper_runs (name TEXT PRIMARY KEY, started_at TEXT);
CREATE TABLE IF NOT EXISTS approvals (name TEXT PRIMARY KEY, time TEXT, capital_pct REAL);
CREATE TABLE IF NOT EXISTS refresh_tokens (jti TEXT PRIMARY KEY, revoked INTEGER DEFAULT 0);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Store:
    def __init__(self, path: str):
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def _exec(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            cur = self.conn.execute(sql, args)
            rows = cur.fetchall()
            self.conn.commit()
            return rows

    # kv
    def get(self, key: str, default: Any = None) -> Any:
        rows = self._exec("SELECT value FROM kv WHERE key=?", (key,))
        return json.loads(rows[0]["value"]) if rows else default

    def put(self, key: str, value: Any) -> None:
        self._exec("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))

    # événements
    def event(self, kind: str, detail: str, now: datetime | None = None) -> None:
        self._exec("INSERT INTO events(time,kind,detail) VALUES(?,?,?)", ((now or utcnow()).isoformat(), kind, detail))

    def events(self, limit: int = 100) -> list[dict]:
        return [dict(r) for r in self._exec("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))]

    # apports
    def add_deposit(self, amount_fcfa: float, note: str, now: datetime | None = None) -> None:
        self._exec("INSERT INTO deposits(time,amount_fcfa,note) VALUES(?,?,?)", ((now or utcnow()).isoformat(), amount_fcfa, note))

    def deposits(self) -> list[dict]:
        return [dict(r) for r in self._exec("SELECT * FROM deposits ORDER BY id")]

    # dry-run et validations
    def start_paper(self, name: str, now: datetime | None = None) -> None:
        self._exec("INSERT OR IGNORE INTO paper_runs(name,started_at) VALUES(?,?)", (name, (now or utcnow()).isoformat()))

    def paper_started(self, name: str) -> datetime | None:
        rows = self._exec("SELECT started_at FROM paper_runs WHERE name=?", (name,))
        return datetime.fromisoformat(rows[0]["started_at"]) if rows else None

    def approve(self, name: str, capital_pct: float, now: datetime | None = None) -> None:
        self._exec("INSERT OR REPLACE INTO approvals(name,time,capital_pct) VALUES(?,?,?)", (name, (now or utcnow()).isoformat(), capital_pct))

    def approval(self, name: str) -> dict | None:
        rows = self._exec("SELECT * FROM approvals WHERE name=?", (name,))
        return dict(rows[0]) if rows else None

    # jetons
    def register_refresh(self, jti: str) -> None:
        self._exec("INSERT OR IGNORE INTO refresh_tokens(jti) VALUES(?)", (jti,))

    def refresh_valid(self, jti: str) -> bool:
        rows = self._exec("SELECT revoked FROM refresh_tokens WHERE jti=?", (jti,))
        return bool(rows) and rows[0]["revoked"] == 0

    def revoke_refresh(self, jti: str | None = None) -> None:
        if jti is None:
            self._exec("UPDATE refresh_tokens SET revoked=1")
        else:
            self._exec("UPDATE refresh_tokens SET revoked=1 WHERE jti=?", (jti,))
