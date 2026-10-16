"""Chargement des données de marché (clôtures en UTC).

Source publique Binance (pas de clé API nécessaire pour les bougies). Endpoint à
vérifier dans la doc officielle si Binance le modifie.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

import pandas as pd

BINANCE_KLINES = "https://data-api.binance.vision/api/v3/klines"


def fetch_binance_closes(symbol: str = "BTCUSDT", interval: str = "1d", limit: int = 1000, timeout: int = 20) -> pd.Series:
    query = urllib.parse.urlencode({"symbol": symbol, "interval": interval, "limit": limit})
    with urllib.request.urlopen(f"{BINANCE_KLINES}?{query}", timeout=timeout) as resp:
        rows = json.loads(resp.read())
    # Ligne kline : [open_time, open, high, low, close, volume, close_time, ...]
    closes = pd.Series(
        [float(r[4]) for r in rows],
        index=pd.to_datetime([int(r[6]) for r in rows], unit="ms", utc=True).floor("s"),
        name="close",
    )
    # La dernière bougie est encore ouverte : la retirer évite d'utiliser un prix non final.
    return closes.iloc[:-1]


def load_csv_closes(path: str) -> pd.Series:
    """CSV avec colonnes `timestamp` (UTC) et `close`."""
    df = pd.read_csv(path)
    idx = pd.to_datetime(df["timestamp"], utc=True)
    return pd.Series(df["close"].astype(float).to_numpy(), index=idx, name="close").sort_index()
