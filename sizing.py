"""
Lógica R (respetada tal cual el brief). Es AVISO, no ejecución: solo calcula
niveles y tamaño para mostrarlos, no coloca ninguna orden.

  - Entrada        = cierre de la vela que disparó.
  - Stop           = al otro lado del nivel que se rompió, con un buffer:
                       long  -> bajo el SOPORTE swing:  support  * (1 - buffer)
                       short -> sobre la RESISTENCIA:    resistance * (1 + buffer)
  - Riesgo (1R)    = abs(entrada - stop)              [en puntos de precio]
  - Tamaño (BTC)   = riesgo_usdt / riesgo_puntos      [el apalancamiento NO
                     cambia el riesgo, solo el margen]
  - Margen bloq.   = (tamaño * entrada) / apalancamiento
  - TP 1R/2R/3R    = entrada ± riesgo_puntos * R según dirección
  - Break-even     = entrada (recordatorio: subir el stop aquí en +1R)
"""

from dataclasses import dataclass

from rules import Signal


@dataclass
class RiskPlan:
    direction: str
    entry: float
    stop: float
    level_broken: float     # el nivel de swing que se rompió (soporte usado en long / resist. en short)
    risk_points: float      # 1R en puntos de precio = abs(entrada - stop)
    size_btc: float         # riesgo_usdt / risk_points
    risk_usdt: float
    leverage: int
    notional_usdt: float    # size_btc * entry
    margin_usdt: float      # notional / leverage
    tps: list[float]        # [1R, 2R, 3R]
    breakeven: float        # = entry


def build_plan(sig: Signal, *, risk_usdt: float, leverage: int,
               stop_buffer_pct: float) -> RiskPlan:
    entry = sig.price

    if sig.direction == "long":
        # El stop va bajo el SOPORTE swing reciente (no bajo la resistencia rota).
        level = sig.support
        stop = level * (1 - stop_buffer_pct)
        sign = 1
    else:
        level = sig.resistance
        stop = level * (1 + stop_buffer_pct)
        sign = -1

    risk_points = abs(entry - stop)
    if risk_points <= 0:
        raise ValueError(f"risk_points no positivo (entry={entry}, stop={stop})")

    size_btc = risk_usdt / risk_points
    notional = size_btc * entry
    margin = notional / leverage
    tps = [entry + sign * risk_points * r for r in (1, 2, 3)]

    return RiskPlan(
        direction=sig.direction,
        entry=entry,
        stop=stop,
        level_broken=level,
        risk_points=risk_points,
        size_btc=size_btc,
        risk_usdt=risk_usdt,
        leverage=leverage,
        notional_usdt=notional,
        margin_usdt=margin,
        tps=tps,
        breakeven=entry,
    )
