"""RISK GUARD + KILL SWITCH — le gardien indépendant.

Ce module ne dépend d'aucun LLM ni de la stratégie. Il a le dernier mot sur toute
nouvelle entrée. Un HALT ne se lève jamais automatiquement : seul l'opérateur peut
redémarrer, avec une phrase de confirmation explicite.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum

from sentinelle.config import MAX_LEVERAGE, RiskLimits

RESET_CONFIRMATION = "JE CONFIRME LE REDEMARRAGE"


class Status(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED_DAILY = "PAUSED_DAILY"  # perte du jour atteinte, reprise le lendemain (UTC)
    PAUSED_LOSS_STREAK = "PAUSED_LOSS_STREAK"  # série de pertes, pause temporisée
    HALTED = "HALTED"  # kill switch : redémarrage manuel obligatoire


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    side: str  # "buy" pour une entrée ; les sorties ne passent pas par ce contrôle
    entry_price: float
    stop_price: float | None
    notional: float
    market_type: str = "spot"
    leverage: float = 1.0


@dataclass(frozen=True)
class OpenPosition:
    symbol: str
    notional: float


@dataclass(frozen=True)
class Decision:
    approved: bool
    reasons: tuple[str, ...]


def _utc(now: datetime) -> datetime:
    if now.tzinfo is None:
        raise ValueError("Les horodatages doivent être en UTC explicite.")
    return now.astimezone(timezone.utc)


@dataclass
class GuardState:
    equity_peak: float
    day_start_equity: float
    current_day: str
    last_equity: float
    consecutive_losses: int = 0
    status: Status = Status.ACTIVE
    pause_until: str | None = None
    halt_reason: str | None = None
    events: list[dict] = field(default_factory=list)


class RiskGuard:
    def __init__(self, limits: RiskLimits, initial_equity: float, now: datetime):
        if initial_equity <= 0:
            raise ValueError("Capital initial invalide.")
        now = _utc(now)
        self.limits = limits
        self.state = GuardState(
            equity_peak=initial_equity,
            day_start_equity=initial_equity,
            current_day=now.date().isoformat(),
            last_equity=initial_equity,
        )

    # --- Journal --------------------------------------------------------------
    def _log(self, now: datetime, kind: str, detail: str) -> None:
        self.state.events.append({"time": now.isoformat(), "kind": kind, "detail": detail})

    def _halt(self, now: datetime, reason: str) -> None:
        if self.state.status != Status.HALTED:
            self.state.status = Status.HALTED
            self.state.halt_reason = reason
            self.state.pause_until = None
            self._log(now, "HALT", reason)

    # --- Mises à jour ---------------------------------------------------------
    def _refresh(self, now: datetime) -> None:
        """Change de jour et lève les pauses temporaires expirées (jamais un HALT)."""
        day = now.date().isoformat()
        if day != self.state.current_day:
            self.state.current_day = day
            self.state.day_start_equity = self.state.last_equity
            if self.state.status == Status.PAUSED_DAILY:
                self.state.status = Status.ACTIVE
                self._log(now, "RESUME", "Nouveau jour UTC : reprise après pause journalière.")
        if (
            self.state.status == Status.PAUSED_LOSS_STREAK
            and self.state.pause_until
            and now >= datetime.fromisoformat(self.state.pause_until)
        ):
            self.state.status = Status.ACTIVE
            self.state.pause_until = None
            self._log(now, "RESUME", "Fin de la pause après série de pertes.")

    def update_equity(self, equity: float, now: datetime) -> Status:
        now = _utc(now)
        self._refresh(now)
        self.state.last_equity = equity
        self.state.equity_peak = max(self.state.equity_peak, equity)

        dd = equity / self.state.equity_peak - 1
        if dd <= -self.limits.max_drawdown:
            self._halt(now, f"Drawdown {dd:.2%} depuis le plus haut (limite -{self.limits.max_drawdown:.0%}).")
            return self.state.status

        day_change = equity / self.state.day_start_equity - 1
        if day_change <= -self.limits.daily_loss_limit and self.state.status == Status.ACTIVE:
            self.state.status = Status.PAUSED_DAILY
            self._log(now, "PAUSE", f"Perte du jour {day_change:.2%} : plus d'entrées aujourd'hui.")
        return self.state.status

    def adjust_for_cashflow(self, amount: float, now: datetime) -> None:
        """Apport (>0) ou mise à l'abri / retrait (<0) : ce n'est ni un gain ni une perte.

        On décale les références (plus haut, début de journée) du même montant, sinon
        un retrait ressemblerait à un drawdown et un apport masquerait une vraie perte.
        """
        now = _utc(now)
        new_last = self.state.last_equity + amount
        if new_last <= 0:
            raise ValueError("Mouvement de fonds supérieur au capital.")
        self.state.last_equity = new_last
        self.state.equity_peak = max(self.state.equity_peak + amount, 1e-9)
        self.state.day_start_equity = max(self.state.day_start_equity + amount, 1e-9)
        self._log(now, "CASHFLOW", f"Mouvement de fonds {amount:+.2f} (références ajustées).")

    def record_trade_result(self, pnl: float, now: datetime) -> None:
        now = _utc(now)
        self._refresh(now)
        if pnl < 0:
            self.state.consecutive_losses += 1
        else:
            self.state.consecutive_losses = 0
        n = self.state.consecutive_losses
        if n >= self.limits.losses_before_pause and self.state.status == Status.ACTIVE:
            until = now + timedelta(hours=self.limits.loss_streak_pause_hours)
            self.state.status = Status.PAUSED_LOSS_STREAK
            self.state.pause_until = until.isoformat()
            self._log(now, "PAUSE", f"{n} pertes consécutives : pause jusqu'au {until.isoformat()}.")

    def check_live_performance(
        self,
        live_sharpe_30d: float,
        backtest_sharpe: float,
        current_drawdown: float,
        backtest_max_drawdown: float,
        now: datetime,
    ) -> Status:
        """Kill conditions définies AVANT déploiement (drawdowns en valeurs négatives)."""
        now = _utc(now)
        if backtest_sharpe > 0 and live_sharpe_30d < 0.5 * backtest_sharpe:
            self._halt(now, f"Sharpe live {live_sharpe_30d:.2f} < 50 % du backtest {backtest_sharpe:.2f}.")
        elif current_drawdown < 1.5 * backtest_max_drawdown:
            self._halt(now, f"Drawdown {current_drawdown:.2%} > 1,5 × drawdown max du backtest.")
        return self.state.status

    def emergency_stop(self, now: datetime, reason: str = "Arrêt d'urgence opérateur.") -> None:
        self._halt(_utc(now), reason)

    def manual_reset(self, confirmation: str, now: datetime) -> bool:
        now = _utc(now)
        if self.state.status != Status.HALTED:
            return False
        if confirmation != RESET_CONFIRMATION:
            self._log(now, "RESET_REFUSED", "Phrase de confirmation incorrecte.")
            return False
        self.state.status = Status.ACTIVE
        self.state.halt_reason = None
        self.state.consecutive_losses = 0
        # Nouveau point de référence : sinon le drawdown passé redéclencherait le HALT.
        self.state.equity_peak = self.state.last_equity
        self.state.day_start_equity = self.state.last_equity
        self._log(now, "RESET", "Redémarrage manuel validé par l'opérateur.")
        return True

    # --- Contrôle d'un ordre ----------------------------------------------------
    def current_risk_pct(self) -> float:
        base = self.limits.risk_per_trade
        if self.state.consecutive_losses >= self.limits.losses_before_risk_halved:
            return base / 2
        return base

    def check_new_order(
        self,
        order: OrderRequest,
        open_positions: list[OpenPosition],
        equity: float,
        now: datetime,
        last_data_time: datetime | None = None,
    ) -> Decision:
        now = _utc(now)
        self._refresh(now)
        reasons: list[str] = []
        lim = self.limits

        if self.state.status != Status.ACTIVE:
            reasons.append(f"Système en statut {self.state.status.value} : aucune nouvelle entrée.")
        if order.market_type != "spot":
            reasons.append("Marché non spot interdit (pas de futures, pas de marge).")
        if order.leverage != MAX_LEVERAGE:
            reasons.append("Levier interdit.")
        if order.side != "buy":
            reasons.append("Seules les entrées longues spot passent par ce contrôle.")
        if order.symbol not in lim.whitelist:
            reasons.append(f"{order.symbol} hors de la liste autorisée.")
        if order.stop_price is None or not 0 < order.stop_price < order.entry_price:
            reasons.append("Stop-loss obligatoire, strictement sous le prix d'entrée.")
        if order.notional < lim.min_notional_usdt:
            reasons.append("Montant sous le minimum de l'exchange.")
        if order.notional > equity * lim.max_position_pct + 1e-9:
            reasons.append(f"Position > {lim.max_position_pct:.0%} du capital.")
        exposure = sum(p.notional for p in open_positions)
        if exposure + order.notional > equity * lim.max_total_exposure + 1e-9:
            reasons.append(f"Exposition totale > {lim.max_total_exposure:.0%} du capital.")
        if len(open_positions) >= lim.max_positions:
            reasons.append(f"Déjà {len(open_positions)} positions ouvertes (max {lim.max_positions}).")
        if any(p.symbol == order.symbol for p in open_positions):
            reasons.append("Position déjà ouverte sur ce symbole (pas de renfort / martingale).")
        if last_data_time is None or (now - _utc(last_data_time)).total_seconds() > lim.max_data_staleness_seconds:
            reasons.append("Données de marché absentes ou périmées.")

        if order.stop_price is not None and 0 < order.stop_price < order.entry_price:
            effective_stop = order.stop_price * (1 - lim.stop_slippage_bps / 1e4)
            risk = order.notional * (order.entry_price - effective_stop) / order.entry_price
            allowed = equity * self.current_risk_pct()
            if risk > allowed * 1.001:
                reasons.append(f"Risque de l'ordre {risk:.2f} > risque autorisé {allowed:.2f}.")

        decision = Decision(approved=not reasons, reasons=tuple(reasons) or ("OK",))
        self._log(now, "ORDER_APPROVED" if decision.approved else "ORDER_REJECTED", "; ".join(decision.reasons))
        return decision

    # --- Persistance -------------------------------------------------------------
    def to_json(self) -> str:
        data = asdict(self.state)
        data["status"] = self.state.status.value
        return json.dumps(data, ensure_ascii=False)

    @classmethod
    def from_json(cls, limits: RiskLimits, payload: str) -> "RiskGuard":
        data = json.loads(payload)
        data["status"] = Status(data["status"])
        guard = cls.__new__(cls)
        guard.limits = limits
        guard.state = GuardState(**data)
        return guard
