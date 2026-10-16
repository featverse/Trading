"""SUPERVISEUR — boucle indépendante qui relie le bot, le gardien et les paliers.

Toutes les minutes :
1. lit le solde et les positions du bot Freqtrade ;
2. met à jour le gardien (perte du jour, drawdown, série de pertes) ;
3. détecte les apports / retraits : variation du solde − variation du profit de trading.
   Un mouvement de fonds n'est ni un gain ni une perte : les références du gardien et des
   paliers sont ajustées automatiquement, sans déclaration manuelle (pas de course) ;
4. si le gardien n'est plus ACTIVE : ordonne au bot d'arrêter toute nouvelle entrée ;
5. détecte les paliers FCFA atteints et le montant à mettre à l'abri.

Le bot demande aussi l'autorisation au gardien AVANT chaque entrée (check_entry) :
si le superviseur est injoignable ou ses données périmées, la réponse est NON.
"""

from __future__ import annotations

import threading
from dataclasses import asdict
from datetime import datetime, timezone

from sentinelle.api.freqtrade_client import FreqtradeAPI, FreqtradeError
from sentinelle.api.settings import Settings
from sentinelle.api.store import Store
from sentinelle.config import RiskLimits
from sentinelle.risk.guard import Decision, OpenPosition, OrderRequest, RiskGuard, Status
from sentinelle.risk.tiers import MilestoneTracker, tier_for

FEED_FAILURES_BEFORE_ALERT = 3
CASHFLOW_MIN_USDT = 1.0  # en dessous : arrondis / frais, ignorés


class Supervisor:
    def __init__(self, settings: Settings, store: Store, freqtrade: FreqtradeAPI, limits: RiskLimits = RiskLimits()):
        self.settings = settings
        self.store = store
        self.ft = freqtrade
        self.limits = limits
        self.lock = threading.RLock()
        raw = store.get("guard")
        self.guard = RiskGuard.from_json(limits, raw) if raw else None
        tracker = store.get("milestones")
        self.tracker = MilestoneTracker(**tracker) if tracker else MilestoneTracker(initial_capital=settings.initial_capital_fcfa)
        self.feed_failures = 0

    # --- utilitaires ---------------------------------------------------------------
    def fcfa(self, usdt: float) -> float:
        return usdt * self.settings.usdt_to_fcfa

    def _save(self) -> None:
        if self.guard is not None:
            self.store.put("guard", self.guard.to_json())
        self.store.put("milestones", asdict(self.tracker))

    def _cache(self) -> dict:
        return self.store.get("feed", {})

    # --- boucle -------------------------------------------------------------------
    def tick(self, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        with self.lock:
            try:
                equity = self.ft.balance_usdt()
                profit = self.ft.profit_total_usdt()
                opens = self.ft.open_trades()
                closed = self.ft.closed_trades(limit=100)
            except FreqtradeError as exc:
                self.feed_failures += 1
                if self.feed_failures == FEED_FAILURES_BEFORE_ALERT:
                    self.store.event("FEED_DOWN", f"Bot injoignable depuis {self.feed_failures} cycles : {exc}", now)
                return
            if self.feed_failures >= FEED_FAILURES_BEFORE_ALERT:
                self.store.event("FEED_UP", "Liaison avec le bot rétablie.", now)
            self.feed_failures = 0

            prev = self._cache()
            cashflow = 0.0
            if prev and "profit_usdt" in prev:
                cashflow = (equity - prev["equity_usdt"]) - (profit - prev["profit_usdt"])

            positions = [{"symbol": t.get("pair"), "notional": float(t.get("stake_amount", 0.0))} for t in opens]
            self.store.put(
                "feed", {"equity_usdt": equity, "profit_usdt": profit, "positions": positions, "updated_at": now.isoformat()}
            )

            just_created = self.guard is None
            if just_created:
                self.guard = RiskGuard(self.limits, equity, now)
                self.store.event("GUARD_INIT", f"Gardien initialisé avec {equity:.2f} USDT.", now)
            elif abs(cashflow) >= CASHFLOW_MIN_USDT:
                self.guard.adjust_for_cashflow(cashflow, now)
                cash_fcfa = self.fcfa(cashflow)
                if cashflow > 0:
                    self.tracker.deposit(cash_fcfa)
                    self.store.event("DEPOSIT_DETECTED", f"Apport détecté : {cash_fcfa:+,.0f} FCFA.", now)
                else:
                    self.tracker.total_secured += -cash_fcfa
                    self.tracker.equity_at_last_milestone = max(0.0, self.tracker.equity_at_last_milestone + cash_fcfa)
                    self.store.event("WITHDRAWAL_DETECTED", f"Retrait / mise à l'abri détecté : {cash_fcfa:+,.0f} FCFA.", now)

            seen = set(self.store.get("seen_trades", []))
            for trade in sorted(closed, key=lambda t: t.get("trade_id", 0)):
                tid = trade.get("trade_id")
                if tid is None or tid in seen or trade.get("is_open"):
                    continue
                seen.add(tid)
                if just_created:
                    continue  # l'historique antérieur au gardien ne compte pas dans la série
                self.guard.record_trade_result(float(trade.get("profit_abs", 0.0)), now)
            self.store.put("seen_trades", sorted(seen))

            before = self.guard.state.status
            status = self.guard.update_equity(equity, now)
            if status != Status.ACTIVE and before == Status.ACTIVE:
                self.store.event(status.value, self.guard.state.halt_reason or "Pause de protection.", now)
                self._stop_bot_entries(now)

            to_secure = self.tracker.check(self.fcfa(equity))
            if to_secure > 0:
                self.store.event(
                    "MILESTONE",
                    f"Palier {self.tracker.last_milestone:,.0f} FCFA atteint. À mettre à l'abri : {to_secure:,.0f} FCFA.",
                    now,
                )
            self._save()

    def _stop_bot_entries(self, now: datetime) -> None:
        try:
            self.ft.stop_entries()
            self.store.event("BOT_ENTRIES_STOPPED", "Le bot n'ouvre plus de positions.", now)
        except FreqtradeError as exc:
            self.store.event("BOT_STOP_FAILED", f"Impossible d'arrêter les entrées du bot : {exc}", now)

    # --- actions ------------------------------------------------------------------
    def check_entry(self, pair: str, rate: float, stop_rate: float, notional: float, now: datetime | None = None) -> Decision:
        now = now or datetime.now(timezone.utc)
        with self.lock:
            feed = self._cache()
            if self.guard is None or not feed:
                return Decision(False, ("Gardien pas encore initialisé.",))
            order = OrderRequest(symbol=pair, side="buy", entry_price=rate, stop_price=stop_rate, notional=notional)
            positions = [OpenPosition(p["symbol"], p["notional"]) for p in feed.get("positions", [])]
            decision = self.guard.check_new_order(
                order, positions, feed["equity_usdt"], now, last_data_time=datetime.fromisoformat(feed["updated_at"])
            )
            self._save()
            return decision

    def emergency_stop(self, exit_all: bool, now: datetime | None = None) -> list[str]:
        now = now or datetime.now(timezone.utc)
        notes = []
        with self.lock:
            if self.guard is None:
                self.guard = RiskGuard(self.limits, max(self._cache().get("equity_usdt", 1.0), 1e-6), now)
            self.guard.emergency_stop(now)
            self.store.event("EMERGENCY_STOP", "Arrêt d'urgence déclenché depuis l'application.", now)
            try:
                self.ft.stop_entries()
                notes.append("Nouvelles entrées bloquées.")
                if exit_all:
                    self.ft.exit_all()
                    notes.append("Ordre de vente de toutes les positions envoyé.")
            except FreqtradeError as exc:
                notes.append(f"ATTENTION : le bot n'a pas répondu ({exc}). Vérifier sur Binance.")
                self.store.event("BOT_STOP_FAILED", str(exc), now)
            self._save()
        return notes

    def reset(self, confirmation: str, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        with self.lock:
            ok = self.guard is not None and self.guard.manual_reset(confirmation, now)
            if ok:
                self.store.event("RESET", "Redémarrage validé par l'opérateur.", now)
            self._save()
            return ok

    def log_planned_deposit(self, amount_fcfa: float, note: str, now: datetime | None = None) -> None:
        """Journal du plan d'épargne (Mobile Money). N'agit PAS sur le gardien : les
        mouvements réels sont détectés automatiquement sur le compte."""
        now = now or datetime.now(timezone.utc)
        if amount_fcfa <= 0:
            raise ValueError("Montant d'apport invalide.")
        self.store.add_deposit(amount_fcfa, note, now)
        self.store.event("DEPOSIT_LOGGED", f"Apport noté : {amount_fcfa:,.0f} FCFA ({note}).", now)

    def snapshot(self) -> dict:
        with self.lock:
            feed = self._cache()
            equity = feed.get("equity_usdt")
            equity_fcfa = self.fcfa(equity) if equity is not None else None
            tier = tier_for(equity_fcfa or self.settings.initial_capital_fcfa)
            g = self.guard.state if self.guard else None
            next_milestone = self.tracker.last_milestone + self.tracker.step_fcfa
            return {
                "status": g.status.value if g else "WAITING_FOR_BOT",
                "halt_reason": g.halt_reason if g else None,
                "pause_until": g.pause_until if g else None,
                "equity_usdt": equity,
                "equity_fcfa": equity_fcfa,
                "drawdown": (g.last_equity / g.equity_peak - 1) if g else 0.0,
                "day_change": (g.last_equity / g.day_start_equity - 1) if g else 0.0,
                "consecutive_losses": g.consecutive_losses if g else 0,
                "current_risk_pct": self.guard.current_risk_pct() if self.guard else self.limits.risk_per_trade,
                "tier": {"name": tier.name, "description": tier.description, "live_trading": tier.live_trading},
                "next_milestone_fcfa": next_milestone,
                "milestone_progress": min(1.0, (equity_fcfa or 0) / next_milestone) if next_milestone else 0.0,
                "total_secured_fcfa": self.tracker.total_secured,
                "feed": {"ok": self.feed_failures == 0 and bool(feed), "updated_at": feed.get("updated_at")},
                "positions": feed.get("positions", []),
            }
