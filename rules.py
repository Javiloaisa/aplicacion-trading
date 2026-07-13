"""
Regla de confluencia de 3 condiciones sobre la ÚLTIMA VELA CERRADA.

Regla dura: solo hay señal si las 3 condiciones son verdad en la MISMA vela.
Una o dos NO es señal. El estado de las 3 se devuelve siempre (aunque no dispare)
para poder loguearlo y depurar.

Diseño para ampliar (p.ej. divergencias RSI como 4ª condición):
  - `Conditions.divergence` ya existe como campo opcional (None = no evaluada).
  - Implementa el check, rellena ese campo, y `all_pass` lo tendrá en cuenta.
    No hay que tocar sizing/notify/main.

LONG:
  1. RSI cruza al alza el nivel: rsi[-1] > L y rsi[-2] <= L
  2. MACD hist cruza de negativo a positivo: hist[-1] > 0 y hist[-2] <= 0
     (opcional) línea MACD > señal
  3. Precio: cierre > resistencia swing

SHORT (simétrica):
  1. RSI cruza a la baja: rsi[-1] < L y rsi[-2] >= L
  2. MACD hist cruza de positivo a negativo: hist[-1] < 0 y hist[-2] >= 0
     (opcional) línea MACD < señal
  3. Precio: cierre < soporte swing
"""

from dataclasses import dataclass

import pandas as pd

from levels import Levels


@dataclass
class Conditions:
    rsi: bool
    macd: bool
    price: bool
    divergence: bool | None = None   # 4ª condición futura (interfaz lista, NO implementada)

    @property
    def all_pass(self) -> bool:
        base = self.rsi and self.macd and self.price
        if self.divergence is None:
            return base
        return base and self.divergence

    def as_marks(self) -> str:
        def m(x: bool | None) -> str:
            return "✗" if x is False else ("✅" if x else "·")
        s = f"rsi={m(self.rsi)} macd={m(self.macd)} price={m(self.price)}"
        if self.divergence is not None:
            s += f" div={m(self.divergence)}"
        return s


@dataclass
class Signal:
    direction: str            # "long" | "short"
    triggered: bool           # las 3 (o 4) condiciones verdad en la misma vela
    price: float              # cierre de la vela que dispara
    candle_ts: int            # open_time (ms) de esa vela
    conditions: Conditions
    resistance: float
    support: float
    # crudos para depurar / trazabilidad:
    rsi_prev: float
    rsi_curr: float
    hist_prev: float
    hist_curr: float


@dataclass
class Evaluation:
    long: Signal
    short: Signal

    @property
    def fired(self) -> Signal | None:
        """La señal que disparó (o None). RSI cross es mutuamente excluyente:
        una vela no puede cruzar el nivel al alza y a la baja a la vez."""
        if self.long.triggered:
            return self.long
        if self.short.triggered:
            return self.short
        return None


def eval_long(df: pd.DataFrame, levels: Levels, cfg) -> Signal:
    rsi_prev, rsi_curr   = float(df["rsi"].iloc[-2]),  float(df["rsi"].iloc[-1])
    hist_prev, hist_curr = float(df["macd_hist"].iloc[-2]), float(df["macd_hist"].iloc[-1])
    macd_curr, sig_curr  = float(df["macd"].iloc[-1]), float(df["macd_signal"].iloc[-1])
    close = float(df["close"].iloc[-1])

    c_rsi = (rsi_curr > cfg.RSI_LONG_LEVEL) and (rsi_prev <= cfg.RSI_LONG_LEVEL)
    c_macd = (hist_curr > 0) and (hist_prev <= 0)
    if cfg.MACD_REQUIRE_ABOVE_SIGNAL:
        c_macd = c_macd and (macd_curr > sig_curr)
    c_price = close > levels.resistance

    conds = Conditions(rsi=c_rsi, macd=c_macd, price=c_price)
    return Signal(
        direction="long", triggered=conds.all_pass, price=close,
        candle_ts=int(df["open_time"].iloc[-1]), conditions=conds,
        resistance=levels.resistance, support=levels.support,
        rsi_prev=rsi_prev, rsi_curr=rsi_curr,
        hist_prev=hist_prev, hist_curr=hist_curr,
    )


def eval_short(df: pd.DataFrame, levels: Levels, cfg) -> Signal:
    rsi_prev, rsi_curr   = float(df["rsi"].iloc[-2]),  float(df["rsi"].iloc[-1])
    hist_prev, hist_curr = float(df["macd_hist"].iloc[-2]), float(df["macd_hist"].iloc[-1])
    macd_curr, sig_curr  = float(df["macd"].iloc[-1]), float(df["macd_signal"].iloc[-1])
    close = float(df["close"].iloc[-1])

    c_rsi = (rsi_curr < cfg.RSI_SHORT_LEVEL) and (rsi_prev >= cfg.RSI_SHORT_LEVEL)
    c_macd = (hist_curr < 0) and (hist_prev >= 0)
    if cfg.MACD_REQUIRE_ABOVE_SIGNAL:
        c_macd = c_macd and (macd_curr < sig_curr)
    c_price = close < levels.support

    conds = Conditions(rsi=c_rsi, macd=c_macd, price=c_price)
    return Signal(
        direction="short", triggered=conds.all_pass, price=close,
        candle_ts=int(df["open_time"].iloc[-1]), conditions=conds,
        resistance=levels.resistance, support=levels.support,
        rsi_prev=rsi_prev, rsi_curr=rsi_curr,
        hist_prev=hist_prev, hist_curr=hist_curr,
    )


def evaluate(df: pd.DataFrame, levels: Levels, cfg) -> Evaluation:
    """Evalúa la última vela cerrada en ambas direcciones. Devuelve el estado
    completo de las condiciones (para loguear) y, vía .fired, la señal disparada."""
    return Evaluation(
        long=eval_long(df, levels, cfg),
        short=eval_short(df, levels, cfg),
    )
