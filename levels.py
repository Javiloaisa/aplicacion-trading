"""
Niveles de soporte / resistencia.

v1 (simple, a propósito): swing high/low de las últimas N velas cerradas,
EXCLUYENDO la vela que dispara (para que "romper el nivel" no sea circular):

    resistencia = max(high[-N:-1])
    soporte     = min(low[-N:-1])

Este módulo está aislado adrede: para mejorar la detección de niveles luego
(p.ej. pivotes, volumen por precio, niveles psicológicos) basta con añadir aquí
otra función que devuelva un `Levels` y enchufarla en rules.py.
"""

from dataclasses import dataclass

import pandas as pd


@dataclass
class Levels:
    resistance: float
    support: float


def swing_levels(df: pd.DataFrame, n: int = 20) -> Levels:
    """
    Calcula resistencia/soporte sobre la ventana [-n:-1] (las N-1 velas previas a la
    última cerrada). El df debe terminar en la vela que se está evaluando.
    """
    window = df.iloc[-n:-1]
    if window.empty:
        raise ValueError(f"Pocas velas para swing_levels(n={n}): {len(df)} filas")
    return Levels(
        resistance=float(window["high"].max()),
        support=float(window["low"].min()),
    )
