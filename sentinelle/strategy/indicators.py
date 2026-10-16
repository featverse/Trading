"""Indicateurs techniques — données passées UNIQUEMENT.

Ce module est autonome (pandas/numpy seulement) : son code source est recopié tel quel
dans les stratégies Freqtrade générées, pour que le backtest et le bot calculent
exactement les mêmes valeurs.
"""

import numpy as np
import pandas as pd


def ind_close(close: pd.Series, window: int = 1) -> pd.Series:
    return close.astype(float)


def ind_sma(close: pd.Series, window: int) -> pd.Series:
    return close.rolling(window, min_periods=window).mean()


def ind_ema(close: pd.Series, window: int) -> pd.Series:
    out = close.ewm(span=window, adjust=False, min_periods=window).mean()
    return out


def ind_rsi(close: pd.Series, window: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    return rsi.where(avg_loss != 0.0, 100.0).where(avg_gain.notna())


def ind_roc(close: pd.Series, window: int) -> pd.Series:
    return close / close.shift(window) - 1.0


def ind_rolling_max(close: pd.Series, window: int) -> pd.Series:
    # Plus haut des `window` barres PRÉCÉDENTES (exclut la barre courante) : cassure honnête.
    return close.shift(1).rolling(window, min_periods=window).max()


def ind_rolling_min(close: pd.Series, window: int) -> pd.Series:
    return close.shift(1).rolling(window, min_periods=window).min()


def ind_volatility(close: pd.Series, window: int) -> pd.Series:
    return np.log(close / close.shift(1)).rolling(window, min_periods=window).std()


INDICATORS = {
    "close": ind_close,
    "sma": ind_sma,
    "ema": ind_ema,
    "rsi": ind_rsi,
    "roc": ind_roc,
    "rolling_max": ind_rolling_max,
    "rolling_min": ind_rolling_min,
    "volatility": ind_volatility,
}
