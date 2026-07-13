"""
Configuración de signal-watcher por variables de entorno / .env.
Mismo patrón que el crypto-agent (clase Config + os.getenv + dotenv).

Es un sistema de AVISO, no de ejecución: aquí no hay claves de API de trading,
solo parámetros de la regla y las credenciales del bot de Telegram de salida.
"""

import os
from dotenv import load_dotenv

load_dotenv()


def _f(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _i(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _b(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


class Config:
    # ── Fuente de datos ────────────────────────────────────────
    BASE_URL      = os.getenv("BITUNIX_BASE_URL", "https://fapi.bitunix.com")
    SYMBOL        = os.getenv("SYMBOL", "BTCUSDT")
    TIMEFRAME     = os.getenv("TIMEFRAME", "1h")          # interval de Bitunix ("1h", "15m"…)
    KLINES_LIMIT  = _i("KLINES_LIMIT", 200)               # velas a bajar (warmup MACD + swing)
    POLL_INTERVAL_SEC = _i("POLL_INTERVAL_SEC", 60)       # cada cuánto sondea

    # ── Indicadores ────────────────────────────────────────────
    RSI_PERIOD    = _i("RSI_PERIOD", 14)
    RSI_LONG_LEVEL  = _f("RSI_LONG_LEVEL", 30)            # cruce al alza (long)
    RSI_SHORT_LEVEL = _f("RSI_SHORT_LEVEL", 70)          # cruce a la baja (short)
    MACD_FAST     = _i("MACD_FAST", 12)
    MACD_SLOW     = _i("MACD_SLOW", 26)
    MACD_SIGNAL   = _i("MACD_SIGNAL", 9)
    # Filtro opcional: exigir además que la línea MACD esté por encima de la señal
    # (long) o por debajo (short). El cruce del histograma ya lo implica casi siempre,
    # por eso viene APAGADO por defecto.
    MACD_REQUIRE_ABOVE_SIGNAL = _b("MACD_REQUIRE_ABOVE_SIGNAL", False)

    # ── Niveles soporte/resistencia (swing high/low) ───────────
    SWING_N       = _i("SWING_N", 20)                     # ventana de velas del swing

    # ── Lógica R (aviso, no ejecución) ─────────────────────────
    RISK_USDT       = _f("RISK_USDT", 10)                 # riesgo fijo por señal (1R en USDT)
    LEVERAGE        = _i("LEVERAGE", 10)                  # solo afecta al MARGEN, no al riesgo
    STOP_BUFFER_PCT = _f("STOP_BUFFER_PCT", 0.001)        # colchón del stop (0.1%) más allá del nivel

    # ── Telegram (bot de salida) ───────────────────────────────
    TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

    # ── Estado (anti-repintado / anti-spam) ────────────────────
    STATE_FILE    = os.getenv("STATE_FILE", "state.json")

    # ── App web / PWA / Web Push ───────────────────────────────
    APP_NAME    = os.getenv("APP_NAME", "Signal Watcher")
    WEB_HOST    = os.getenv("WEB_HOST", "0.0.0.0")
    WEB_PORT    = _i("WEB_PORT", 8095)
    PUSH_ENABLED = _b("PUSH_ENABLED", True)
    # VAPID: identidad del servidor ante el push service. Se autogenera al arrancar
    # si el fichero no existe (NO lo borres ni lo subas a git: rota las suscripciones).
    VAPID_PRIVATE_KEY_FILE = os.getenv("VAPID_PRIVATE_KEY_FILE", "vapid_private.pem")
    VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:admin@example.com")
    SUBSCRIPTIONS_FILE = os.getenv("SUBSCRIPTIONS_FILE", "subscriptions.json")
    SIGNALS_FILE       = os.getenv("SIGNALS_FILE", "signals.json")

    @classmethod
    def telegram_enabled(cls) -> bool:
        return bool(cls.TELEGRAM_TOKEN and cls.TELEGRAM_CHAT_ID)
