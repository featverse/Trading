import numpy as np
import pandas as pd
import pytest


def make_prices(n: int = 600, seed: int = 0, drift: float = 0.0, vol: float = 0.03) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2022-01-01", periods=n, freq="D", tz="UTC")
    log_ret = rng.normal(drift, vol, n)
    log_ret[0] = 0.0
    return pd.Series(20_000 * np.exp(np.cumsum(log_ret)), index=idx, name="close")


@pytest.fixture
def prices() -> pd.Series:
    return make_prices()
