"""
Klines de Bitunix (endpoint público, sin firma) + lógica de vela CERRADA.

Endpoint confirmado en vivo:
  GET https://fapi.bitunix.com/api/v1/futures/market/kline
      ?symbol=BTCUSDT&interval=1h&limit=200

Respuesta: {"code":0,"data":[ {open,high,low,close,quoteVol,baseVol,time}, ... ]}
  - Los valores son STRINGS  -> se castean a float.
  - `time` es el open-time en ms.
  - La lista viene en orden DESCENDENTE (la más nueva primero) -> se ordena ASC.
  - La vela más reciente suele ser la que aún se está formando; NO la evaluamos.
    El cierre se deduce de open_time + interval_ms <= now  (anti-repintado robusto,
    no depende de "quitar la última fila").
"""

import json
import time
import urllib.parse
import urllib.request

import pandas as pd

KLINE_PATH = "/api/v1/futures/market/kline"

# Unidades de intervalo -> milisegundos.
_UNIT_MS = {"m": 60_000, "h": 3_600_000, "d": 86_400_000}


def interval_to_ms(interval: str) -> int:
    """'1h' -> 3600000, '15m' -> 900000, '1d' -> 86400000."""
    interval = interval.strip().lower()
    unit = interval[-1]
    if unit not in _UNIT_MS:
        raise ValueError(f"Intervalo no soportado: {interval!r}")
    return int(interval[:-1]) * _UNIT_MS[unit]


def _http_get_json(url: str, retries: int = 3, timeout: int = 15) -> dict:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "signal-watcher/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:  # noqa: BLE001 - queremos reintentar cualquier fallo de red
            last_err = e
            if attempt < retries - 1:
                time.sleep(3)
    raise RuntimeError(f"GET {url} falló {retries}x: {last_err}")


def fetch_klines(symbol: str, interval: str, limit: int = 200,
                 base_url: str = "https://fapi.bitunix.com") -> pd.DataFrame:
    """
    Descarga velas y devuelve un DataFrame ASCENDENTE (la más antigua primero) con
    columnas: open_time (int ms), open, high, low, close, volume (float).
    Incluye la vela en formación si la API la devuelve; usar drop_unclosed() para quitarla.
    """
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    url = f"{base_url}{KLINE_PATH}?{urllib.parse.urlencode(params)}"
    data = _http_get_json(url)

    if str(data.get("code")) not in ("0", "200", "None"):
        raise RuntimeError(f"Bitunix kline error: {data}")
    rows = data.get("data") or []
    if not isinstance(rows, list) or not rows:
        raise RuntimeError(f"Bitunix kline sin datos: {data}")

    df = pd.DataFrame([
        {
            "open_time": int(r["time"]),
            "open":  float(r["open"]),
            "high":  float(r["high"]),
            "low":   float(r["low"]),
            "close": float(r["close"]),
            # El volumen no lo usa la regla; se guarda de forma defensiva.
            "volume": float(r.get("quoteVol") or r.get("baseVol") or 0.0),
        }
        for r in rows
    ])
    df = df.sort_values("open_time").drop_duplicates("open_time").reset_index(drop=True)
    return df


def drop_unclosed(df: pd.DataFrame, interval: str, now_ms: int | None = None) -> pd.DataFrame:
    """
    Devuelve solo velas CERRADAS: conserva las filas cuyo open_time + interval_ms <= now.
    Así nunca evaluamos la vela en formación (evita repintado), venga o no en la respuesta.
    """
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    step = interval_to_ms(interval)
    closed = df[df["open_time"] + step <= now_ms]
    return closed.reset_index(drop=True)


def last_closed_ts(df: pd.DataFrame) -> int:
    """open_time (ms) de la última vela cerrada del DataFrame."""
    return int(df["open_time"].iloc[-1])
