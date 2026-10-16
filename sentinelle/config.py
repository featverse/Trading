"""Limites de risque de SENTINELLE.

Deux niveaux :
- les PLAFONDS ABSOLUS (constantes du module) : aucune configuration ne peut les
  dépasser. Les modifier exige un changement de code, une revue et une nouvelle version.
- les LIMITES ACTIVES (RiskLimits) : réglables, mais toujours sous les plafonds.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --- Plafonds absolus (non configurables) -----------------------------------
SPOT_ONLY: bool = True
MAX_LEVERAGE: float = 1.0
HARD_MAX_RISK_PER_TRADE: float = 0.01  # 1 % du capital
HARD_MAX_POSITION_PCT: float = 0.20  # 20 % du capital par position
HARD_MAX_TOTAL_EXPOSURE: float = 0.60  # 40 % minimum toujours en USDT
HARD_MAX_DAILY_LOSS: float = 0.03  # -3 % sur la journée
HARD_MAX_DRAWDOWN: float = 0.10  # -10 % depuis le plus haut
HARD_MAX_POSITIONS: int = 3

# Minimum de notionnel d'un ordre spot Binance (≈ 5 USDT, à vérifier par paire
# via exchangeInfo / filtre NOTIONAL : la valeur exacte varie selon le symbole).
DEFAULT_MIN_NOTIONAL_USDT: float = 5.0

DEFAULT_WHITELIST: tuple[str, ...] = ("BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT")


class RiskConfigError(ValueError):
    """Configuration de risque refusée car elle dépasse un plafond absolu."""


@dataclass(frozen=True)
class RiskLimits:
    risk_per_trade: float = 0.005  # 0,5 % au démarrage
    max_position_pct: float = HARD_MAX_POSITION_PCT
    max_total_exposure: float = HARD_MAX_TOTAL_EXPOSURE
    max_positions: int = HARD_MAX_POSITIONS
    daily_loss_limit: float = HARD_MAX_DAILY_LOSS
    max_drawdown: float = HARD_MAX_DRAWDOWN
    losses_before_risk_halved: int = 4
    losses_before_pause: int = 6
    loss_streak_pause_hours: int = 48
    max_data_staleness_seconds: int = 180
    stop_slippage_bps: float = 20.0  # marge de sécurité : le stop peut glisser
    min_notional_usdt: float = DEFAULT_MIN_NOTIONAL_USDT
    whitelist: tuple[str, ...] = field(default=DEFAULT_WHITELIST)

    def __post_init__(self) -> None:
        checks = [
            (0 < self.risk_per_trade <= HARD_MAX_RISK_PER_TRADE, "risk_per_trade"),
            (0 < self.max_position_pct <= HARD_MAX_POSITION_PCT, "max_position_pct"),
            (0 < self.max_total_exposure <= HARD_MAX_TOTAL_EXPOSURE, "max_total_exposure"),
            (1 <= self.max_positions <= HARD_MAX_POSITIONS, "max_positions"),
            (0 < self.daily_loss_limit <= HARD_MAX_DAILY_LOSS, "daily_loss_limit"),
            (0 < self.max_drawdown <= HARD_MAX_DRAWDOWN, "max_drawdown"),
            (1 <= self.losses_before_risk_halved <= self.losses_before_pause, "losses_*"),
            (self.stop_slippage_bps >= 0, "stop_slippage_bps"),
            (self.min_notional_usdt > 0, "min_notional_usdt"),
            (len(self.whitelist) > 0, "whitelist"),
        ]
        for ok, name in checks:
            if not ok:
                raise RiskConfigError(f"Limite refusée (plafond absolu dépassé ou invalide) : {name}")
