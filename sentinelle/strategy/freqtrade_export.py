"""Génère une stratégie Freqtrade (IStrategy v3) et sa configuration DRY-RUN à partir
d'une StrategySpec validée.

Le code des indicateurs est recopié depuis sentinelle/strategy/indicators.py : backtest
et bot calculent les mêmes valeurs.

À VÉRIFIER dans la doc officielle de la version de Freqtrade déployée (testé contre
l'interface IStrategy v3) : noms des clés `order_types`, format des `protections`.
"""

from __future__ import annotations

import inspect
import json
import textwrap

from sentinelle.config import RiskLimits
from sentinelle.strategy import indicators
from sentinelle.strategy.spec import Condition, Indicator, StrategySpec

TIMEFRAME_CANDLES_PER_DAY = {"4h": 6, "1d": 1}


def _ind_expr(ind: Indicator, params: dict[str, int]) -> str:
    window = params[ind.window] if isinstance(ind.window, str) else ind.window
    return f'ind_{ind.kind}(dataframe["close"], {int(window)})'


def _cond_expr(cond: Condition, params: dict[str, int]) -> str:
    left = _ind_expr(cond.left, params)
    right = _ind_expr(cond.right, params) if cond.right is not None else repr(float(cond.value))
    return f"({left} {cond.op} {right}).fillna(False)"


def class_name(spec: StrategySpec) -> str:
    return "Sentinelle" + "".join(part.capitalize() for part in spec.name.split("_"))


def render_strategy(spec: StrategySpec, params: dict[str, int], limits: RiskLimits = RiskLimits()) -> str:
    entry = " & ".join(_cond_expr(c, params) for c in spec.entry_all)
    exit_ = " | ".join(_cond_expr(c, params) for c in spec.exit_any)
    per_day = TIMEFRAME_CANDLES_PER_DAY[spec.timeframe]
    startup = spec.max_window(params) + 5
    indicator_src = inspect.getsource(indicators).split('"""', 2)[2]  # sans la docstring du module

    return f'''"""Stratégie générée par SENTINELLE — NE PAS MODIFIER À LA MAIN.

Spec : {spec.name} | actif {spec.asset} | timeframe {spec.timeframe} | paramètres {json.dumps(params)}
Mécanisme : {spec.mechanism.replace('"""', "'")}
Contrepartie : {spec.counterparty.replace('"""', "'")}
Invalidation : {spec.invalidation.replace('"""', "'")}

Spot uniquement, pas de levier, pas de vente à découvert. DRY-RUN tant que l'opérateur
n'a pas validé le passage en réel dans l'application.
Illustratif, pas un conseil financier. Aucune garantie de performance.
"""
import json
import os
import urllib.request

from pandas import DataFrame
from freqtrade.strategy import IStrategy
{indicator_src}

class {class_name(spec)}(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "{spec.timeframe}"
    can_short = False
    process_only_new_candles = True
    startup_candle_count = {startup}

    # Pas de prise de profit fixe : la sortie suit les règles de la spec.
    minimal_roi = {{"0": 100.0}}
    stoploss = -{spec.stop_loss_pct:.4f}
    trailing_stop = False

    order_types = {{
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": True,
    }}

    @property
    def protections(self):
        return [
            {{"method": "CooldownPeriod", "stop_duration_candles": 1}},
            {{
                "method": "StoplossGuard",
                "lookback_period_candles": {per_day * 2},
                "trade_limit": {limits.losses_before_risk_halved},
                "stop_duration_candles": {per_day * 2},
                "only_per_pair": False,
            }},
            {{
                "method": "MaxDrawdown",
                "lookback_period_candles": {per_day * 30},
                "trade_limit": 1,
                "stop_duration_candles": {per_day * 30},
                "max_allowed_drawdown": {limits.max_drawdown},
            }},
        ]

    # ── Taille de position : Capital × risque / distance au stop (règle du 1 %) ──
    def custom_stake_amount(self, pair, current_time, current_rate, proposed_stake, min_stake,
                            max_stake, leverage, entry_tag, side, **kwargs) -> float:
        total = self.wallets.get_total_stake_amount()
        stop_distance = abs(self.stoploss) + {limits.stop_slippage_bps / 1e4:.6f}
        stake = total * {limits.risk_per_trade} / stop_distance
        stake = min(stake, total * {limits.max_position_pct}, max_stake)
        if min_stake is not None and stake < min_stake:
            return 0.0  # sous le minimum de l'exchange : on ne trade pas (capital trop petit)
        return stake

    # ── Le gardien SENTINELLE a le dernier mot. Sans réponse : NON. ──
    def confirm_trade_entry(self, pair, order_type, amount, rate, time_in_force, current_time,
                            entry_tag, side, **kwargs) -> bool:
        if side != "long":
            return False
        url = os.environ.get("SENTINELLE_GUARD_URL", "")
        token = os.environ.get("SENTINELLE_INTERNAL_TOKEN", "")
        if not url or not token:
            return False
        body = json.dumps({{
            "pair": pair,
            "rate": float(rate),
            "stop_rate": float(rate) * (1 + self.stoploss),
            "notional": float(amount) * float(rate),
        }}).encode()
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={{"Content-Type": "application/json", "X-Internal-Token": token}})
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                return bool(json.loads(resp.read()).get("approved", False))
        except Exception:
            return False

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        entry = {entry}
        exit_ = {exit_}
        dataframe.loc[entry & ~exit_, "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        exit_ = {exit_}
        dataframe.loc[exit_, "exit_long"] = 1
        return dataframe
'''


def render_config(spec: StrategySpec, dry_run_wallet_usdt: float, limits: RiskLimits = RiskLimits()) -> str:
    """Configuration DRY-RUN. Les secrets passent par variables d'environnement
    (FREQTRADE__EXCHANGE__KEY, FREQTRADE__EXCHANGE__SECRET, FREQTRADE__TELEGRAM__TOKEN...),
    jamais dans ce fichier."""
    config = {
        "dry_run": True,
        "dry_run_wallet": dry_run_wallet_usdt,
        "trading_mode": "spot",
        "stake_currency": "USDT",
        "stake_amount": round(dry_run_wallet_usdt * limits.max_position_pct, 2),
        "max_open_trades": 1,
        "tradable_balance_ratio": limits.max_total_exposure,
        "timeframe": spec.timeframe,
        "strategy": class_name(spec),
        "cancel_open_orders_on_exit": True,
        "unfilledtimeout": {"entry": 10, "exit": 10, "unit": "minutes"},
        "entry_pricing": {"price_side": "same", "use_order_book": True, "order_book_top": 1},
        "exit_pricing": {"price_side": "same", "use_order_book": True, "order_book_top": 1},
        "exchange": {
            "name": "binance",
            "key": "",
            "secret": "",
            "pair_whitelist": [spec.asset],
            "pair_blacklist": [],
        },
        "pairlists": [{"method": "StaticPairList"}],
        "telegram": {"enabled": False, "token": "", "chat_id": ""},
        "api_server": {
            "enabled": True,
            "listen_ip_address": "0.0.0.0",
            "listen_port": 8080,
            "username": "sentinelle",
            "password": "",
            "jwt_secret_key": "",
            "CORS_origins": [],
        },
        "bot_name": f"sentinelle-{spec.name}",
        "initial_state": "running",
        "internals": {"process_throttle_secs": 5},
    }
    return json.dumps(config, indent=2, ensure_ascii=False)


def render_readme(spec: StrategySpec, params: dict[str, int]) -> str:
    return textwrap.dedent(
        f"""\
        # {class_name(spec)} — DRY-RUN

        - Actif : {spec.asset} · timeframe {spec.timeframe} · paramètres {params}
        - Stop-loss : {spec.stop_loss_pct:.1%} (posé sur l'exchange)
        - Mode : **simulation**. Passage en réel uniquement après ≥ 4 semaines de dry-run et
          validation de l'opérateur dans l'application.
        """
    )
