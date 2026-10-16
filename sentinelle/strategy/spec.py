"""Langage de stratégie déclaratif (DSL).

Règle de sécurité centrale : un agent IA ne produit JAMAIS de code exécutable.
Il produit une StrategySpec (données validées), que du code de confiance compile en
signal. Conséquences :
- pas d'exécution de code généré par un LLM, donc pas de sandbox à risque ;
- seuls des indicateurs « passé uniquement » sont disponibles : le look-ahead est
  impossible par construction (et vérifié quand même par le test de troncature) ;
- le nombre de variantes est borné et compté (essais du Deflated Sharpe).
"""

from __future__ import annotations

import itertools
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from sentinelle.config import DEFAULT_WHITELIST
from sentinelle.strategy.indicators import INDICATORS

MAX_GRID_SIZE = 24
MAX_WINDOW = 400

IndicatorKind = Literal["close", "sma", "ema", "rsi", "roc", "rolling_max", "rolling_min", "volatility"]
Asset = Literal[DEFAULT_WHITELIST]  # type: ignore[valid-type]


class Indicator(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: IndicatorKind
    # Entier fixe, ou nom d'un paramètre de `param_grid` (ex. "fast").
    window: int | str = 1


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    left: Indicator
    op: Literal[">", "<"]
    right: Indicator | None = None
    value: float | None = None

    @model_validator(mode="after")
    def _one_rhs(self) -> "Condition":
        if (self.right is None) == (self.value is None):
            raise ValueError("Une condition compare à un indicateur OU à une valeur, pas les deux.")
        return self


class StrategySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{2,40}$")
    asset: Asset
    timeframe: Literal["4h", "1d"]
    mechanism: str = Field(min_length=20, description="Mécanisme économique : qui perd et pourquoi.")
    counterparty: str = Field(min_length=5)
    invalidation: str = Field(min_length=10)
    entry_all: list[Condition] = Field(min_length=1, max_length=4)
    exit_any: list[Condition] = Field(min_length=1, max_length=4)
    stop_loss_pct: float = Field(ge=0.01, le=0.15)
    param_grid: dict[str, list[int]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_params(self) -> "StrategySpec":
        refs: set[str] = set()
        for cond in self.entry_all + self.exit_any:
            for ind in (cond.left, cond.right):
                if ind is None:
                    continue
                if isinstance(ind.window, str):
                    refs.add(ind.window)
                elif not 1 <= ind.window <= MAX_WINDOW:
                    raise ValueError(f"Fenêtre hors bornes : {ind.window}")
        missing = refs - set(self.param_grid)
        if missing:
            raise ValueError(f"Paramètres non définis dans param_grid : {sorted(missing)}")
        unused = set(self.param_grid) - refs
        if unused:
            raise ValueError(f"Paramètres inutilisés (ils gonfleraient N) : {sorted(unused)}")
        for name, values in self.param_grid.items():
            if not values or any(not 2 <= v <= MAX_WINDOW for v in values) or len(set(values)) != len(values):
                raise ValueError(f"Valeurs invalides pour {name}.")
        if self.grid_size() > MAX_GRID_SIZE:
            raise ValueError(f"Grille de {self.grid_size()} variantes > {MAX_GRID_SIZE} : surapprentissage.")
        return self

    def grid_size(self) -> int:
        size = 1
        for values in self.param_grid.values():
            size *= len(values)
        return size

    def grid(self) -> list[dict[str, int]]:
        if not self.param_grid:
            return [{}]
        names = sorted(self.param_grid)
        return [dict(zip(names, combo)) for combo in itertools.product(*(self.param_grid[n] for n in names))]

    def max_window(self, params: dict[str, int]) -> int:
        windows = [1]
        for cond in self.entry_all + self.exit_any:
            for ind in (cond.left, cond.right):
                if ind is not None:
                    windows.append(_resolve(ind.window, params))
        return max(windows)


def _resolve(window: int | str, params: dict[str, int]) -> int:
    return params[window] if isinstance(window, str) else window


def _series(ind: Indicator, close: pd.Series, params: dict[str, int]) -> pd.Series:
    return INDICATORS[ind.kind](close, _resolve(ind.window, params))


def evaluate_condition(cond: Condition, close: pd.Series, params: dict[str, int]) -> pd.Series:
    left = _series(cond.left, close, params)
    right = _series(cond.right, close, params) if cond.right is not None else cond.value
    result = left > right if cond.op == ">" else left < right
    return result.fillna(False).astype(bool)


def compile_signal(spec: StrategySpec, params: dict[str, int]):
    """Retourne une fonction prices -> exposition désirée (0 ou 1), passé uniquement.

    Machine à états : entrée si TOUTES les conditions d'entrée sont vraies, sortie si
    UNE condition de sortie est vraie ou si la clôture passe sous le stop. Le stop est
    évalué à la CLÔTURE (estimation prudente du backtest ; en réel il est posé sur
    l'exchange et le slippage est couvert par RiskLimits.stop_slippage_bps).
    """
    if set(params) != set(spec.param_grid):
        raise ValueError("Paramètres incomplets pour cette stratégie.")

    def signal_fn(close: pd.Series) -> pd.Series:
        entry = np.logical_and.reduce([evaluate_condition(c, close, params).to_numpy() for c in spec.entry_all])
        exit_ = np.logical_or.reduce([evaluate_condition(c, close, params).to_numpy() for c in spec.exit_any])
        prices = close.to_numpy(dtype=float)
        out = np.zeros(len(close))
        in_pos, entry_price = False, 0.0
        for i in range(len(close)):
            if in_pos:
                stopped = prices[i] <= entry_price * (1 - spec.stop_loss_pct)
                if exit_[i] or stopped:
                    in_pos = False
            elif entry[i] and not exit_[i]:
                in_pos = True
                # Exécution à la barre suivante : le prix d'entrée réel sera connu plus tard ;
                # on prend la clôture du signal comme référence (connue à t).
                entry_price = prices[i]
            out[i] = 1.0 if in_pos else 0.0
        return pd.Series(out, index=close.index)

    return signal_fn
