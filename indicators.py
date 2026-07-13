"""
Indicadores calculados en LOCAL (no se confía en los del exchange).

Se apoyan en el shim `pandas_ta_compat` (sobre la librería `ta`), igual que el
crypto-agent. Añade al DataFrame: rsi, macd, macd_signal, macd_hist.

Importante para el anti-repintado: estas funciones solo AÑADEN columnas; la
regla evalúa siempre sobre la última vela CERRADA (df ya filtrado en data.py).
"""

import pandas as pd

import pandas_ta_compat as pta


def add_indicators(df: pd.DataFrame, cfg) -> pd.DataFrame:
    """
    Devuelve una copia del df con columnas: rsi, macd, macd_signal, macd_hist.
    Lanza ValueError si no hay suficientes velas para el warmup del MACD.
    """
    out = df.copy()
    close = out["close"]

    out["rsi"] = pta.rsi(close, length=cfg.RSI_PERIOD)

    macd_df = pta.macd(
        close,
        fast=cfg.MACD_FAST,
        slow=cfg.MACD_SLOW,
        signal=cfg.MACD_SIGNAL,
    )
    if macd_df is None:
        raise ValueError("MACD no calculable (muy pocas velas para el warmup)")

    f, s, g = cfg.MACD_FAST, cfg.MACD_SLOW, cfg.MACD_SIGNAL
    out["macd"]        = macd_df[f"MACD_{f}_{s}_{g}"]
    out["macd_signal"] = macd_df[f"MACDs_{f}_{s}_{g}"]
    out["macd_hist"]   = macd_df[f"MACDh_{f}_{s}_{g}"]
    return out


def has_warmup(df: pd.DataFrame) -> bool:
    """True si las dos últimas velas tienen indicadores válidos (no NaN)."""
    if len(df) < 2:
        return False
    cols = ["rsi", "macd", "macd_signal", "macd_hist"]
    return not df[cols].iloc[-2:].isnull().any().any()
