"""
Compatibility shim: provides the pandas-ta API surface used in this project,
implemented on top of the `ta` library (Python 3.11+ compatible).

Copiado del crypto-agent para que signal-watcher calcule los indicadores
EXACTAMENTE igual que el bot ya desplegado (mismo `ta`, mismos parámetros).
"""
import pandas as pd
import numpy as np
import ta as _ta


def ema(close: pd.Series, length: int = 14, **_) -> pd.Series:
    return _ta.trend.EMAIndicator(close=close, window=length, fillna=False).ema_indicator()


def rsi(close: pd.Series, length: int = 14, **_) -> pd.Series:
    return _ta.momentum.RSIIndicator(close=close, window=length, fillna=False).rsi()


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9, **_):
    ind = _ta.trend.MACD(
        close=close,
        window_fast=fast,
        window_slow=slow,
        window_sign=signal,
        fillna=False,
    )
    df = pd.DataFrame({
        f'MACD_{fast}_{slow}_{signal}':  ind.macd(),
        f'MACDs_{fast}_{slow}_{signal}': ind.macd_signal(),
        f'MACDh_{fast}_{slow}_{signal}': ind.macd_diff(),
    })
    return df if not df.isnull().all().all() else None


def atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14, **_) -> pd.Series:
    return _ta.volatility.AverageTrueRange(
        high=high, low=low, close=close, window=length, fillna=False
    ).average_true_range()
