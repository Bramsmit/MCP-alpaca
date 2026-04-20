"""
Technische indicatoren in pure pandas (geen externe TA-bibliotheek).

Alle functies verwachten een pandas.DataFrame met kolommen
``high``, ``low``, ``close`` (voor ATR/ADX) of een pandas.Series
(voor EMA). Ze retourneren een Series met dezelfde index als de input.

Wilder's smoothing wordt gebruikt voor ATR en ADX, wat identiek is aan
een EMA met alpha = 1/n (ofwel com = n-1).
"""

from __future__ import annotations

import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average (standaard EMA, span=period)."""
    if period <= 0:
        raise ValueError("period must be > 0")
    return series.ewm(span=period, adjust=False).mean()


def _wilder(series: pd.Series, period: int) -> pd.Series:
    """Wilder-smoothing: EMA met alpha = 1/period (com = period-1)."""
    return series.ewm(alpha=1.0 / period, adjust=False).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    """True Range per bar: max(H-L, |H - prev_close|, |L - prev_close|)."""
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    prev_close = df["close"].astype(float).shift(1)

    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range met Wilder-smoothing."""
    tr = true_range(df)
    return _wilder(tr, period)


def adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """
    Average Directional Index (Wilder).

    Retourneert een DataFrame met kolommen ``plus_di``, ``minus_di``, ``adx``.
    Input DataFrame moet ``high``, ``low``, ``close`` bevatten.
    """
    high = df["high"].astype(float)
    low = df["low"].astype(float)

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = ((up_move > down_move) & (up_move > 0)).astype(float) * up_move.clip(lower=0)
    minus_dm = ((down_move > up_move) & (down_move > 0)).astype(float) * down_move.clip(lower=0)

    tr = true_range(df)
    atr_ = _wilder(tr, period)

    # Voorkom deling door nul tijdens de eerste bars.
    atr_safe = atr_.replace(0, pd.NA)

    plus_di = 100 * _wilder(plus_dm, period) / atr_safe
    minus_di = 100 * _wilder(minus_dm, period) / atr_safe

    di_sum = (plus_di + minus_di).replace(0, pd.NA)
    dx = 100 * (plus_di - minus_di).abs() / di_sum

    adx_series = _wilder(dx.fillna(0), period)

    out = pd.DataFrame(
        {
            "plus_di": plus_di.astype(float),
            "minus_di": minus_di.astype(float),
            "adx": adx_series.astype(float),
        },
        index=df.index,
    )
    return out


def _sanity_check() -> None:
    """Basale sanity-check: constant stijgende prijs -> ADX > 0, EMA oploopt."""
    import numpy as np

    n = 100
    idx = pd.date_range("2025-01-01", periods=n, freq="h")
    close = pd.Series(np.linspace(100, 200, n), index=idx)
    high = close + 0.5
    low = close - 0.5
    df = pd.DataFrame({"high": high, "low": low, "close": close})

    e = ema(close, 20)
    assert e.iloc[-1] > e.iloc[0], "EMA moet stijgen in uptrend"

    a = atr(df, 14)
    assert a.iloc[-1] > 0, "ATR moet > 0"

    dx = adx(df, 14)
    assert dx["plus_di"].iloc[-1] > dx["minus_di"].iloc[-1], "+DI > -DI in uptrend"
    assert dx["adx"].iloc[-1] > 20, "ADX moet duidelijk > 20 in rechte uptrend"

    print("indicators sanity OK:",
          f"ema_last={e.iloc[-1]:.2f}",
          f"atr_last={a.iloc[-1]:.4f}",
          f"adx_last={dx['adx'].iloc[-1]:.2f}",
          f"+DI={dx['plus_di'].iloc[-1]:.2f}",
          f"-DI={dx['minus_di'].iloc[-1]:.2f}")


if __name__ == "__main__":
    _sanity_check()
