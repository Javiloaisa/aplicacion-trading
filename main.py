"""
signal-watcher — motor de vigilancia (loop).

Cada POLL_INTERVAL_SEC: baja velas, comprueba si hay una vela CERRADA nueva,
calcula indicadores + niveles, evalúa la regla de 3 condiciones y, si dispara,
avisa. NO ejecuta órdenes.

El envío del aviso NO vive aquí: run_once/run_loop reciben callbacks
(on_eval, on_signal) y el que llama decide dónde va el aviso:
  - main() (este fichero, standalone)  -> solo Telegram.
  - server.py                          -> Telegram + Web Push (PWA) + panel.

Anti-repintado + anti-spam:
  - Solo se evalúa la última vela cerrada (data.drop_unclosed).
  - Se guarda el open_time de la última vela procesada en STATE_FILE; una vela
    ya procesada no se re-evalúa ni re-notifica (incluso tras un reinicio).

Uso standalone:
  python main.py            # loop (solo Telegram)
  python main.py --once     # un solo ciclo y salir
  python main.py --dry-run  # no envía Telegram (solo loguea)  (o env DRY_RUN=true)
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from config import Config
import data as kdata
from indicators import add_indicators, has_warmup
from levels import swing_levels, Levels
from rules import evaluate, Signal, Evaluation
from sizing import build_plan
from notify import Notifier, format_signal

log = logging.getLogger("signal-watcher")

# Firmas de los callbacks:
#   on_eval(cfg, candle_ts:int, close:float, levels:Levels, ev:Evaluation) -> None
#   on_signal(cfg, sig:Signal, plan:RiskPlan) -> None
OnEval   = Callable[[Config, int, float, Levels, Evaluation], None]
OnSignal = Callable[[Config, Signal, object], None]


# ── Estado persistente ────────────────────────────────────────────────
def load_state(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(path: str, state: dict) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f)
    os.replace(tmp, path)   # escritura atómica


# ── Un ciclo ──────────────────────────────────────────────────────────
def run_once(cfg, state: dict,
             on_eval: Optional[OnEval] = None,
             on_signal: Optional[OnSignal] = None) -> bool:
    """
    Procesa como mucho una vela nueva. Devuelve True si había vela nueva (y por
    tanto se actualizó el estado), False si no había nada nuevo.
    """
    df = kdata.fetch_klines(cfg.SYMBOL, cfg.TIMEFRAME, cfg.KLINES_LIMIT, cfg.BASE_URL)
    df = kdata.drop_unclosed(df, cfg.TIMEFRAME)

    min_rows = max(cfg.SWING_N, cfg.MACD_SLOW + cfg.MACD_SIGNAL, cfg.RSI_PERIOD) + 2
    if len(df) < min_rows:
        log.warning("Pocas velas cerradas (%d < %d); espero al siguiente ciclo", len(df), min_rows)
        return False

    candle_ts = kdata.last_closed_ts(df)
    if state.get("last_candle_ts") == candle_ts:
        return False   # esta vela ya se procesó (nada nuevo)

    df = add_indicators(df, cfg)
    if not has_warmup(df):
        log.warning("Indicadores con NaN en las últimas velas; espero más historia")
        return False

    levels = swing_levels(df, cfg.SWING_N)
    ev = evaluate(df, levels, cfg)

    when = datetime.fromtimestamp(candle_ts / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")
    close = float(df["close"].iloc[-1])
    fired = ev.fired
    verdict = f"→ FIRED {fired.direction.upper()}" if fired else "→ sin señal"
    log.info(
        "[%s UTC] %s %s close=%.2f | res=%.2f sop=%.2f | LONG %s | SHORT %s %s",
        when, cfg.SYMBOL, cfg.TIMEFRAME, close,
        levels.resistance, levels.support,
        ev.long.conditions.as_marks(), ev.short.conditions.as_marks(), verdict,
    )

    if on_eval:
        try:
            on_eval(cfg, candle_ts, close, levels, ev)
        except Exception as e:  # noqa: BLE001 - un fallo de panel no debe cortar el loop
            log.exception("on_eval falló: %s", e)

    if fired:
        try:
            plan = build_plan(
                fired,
                risk_usdt=cfg.RISK_USDT,
                leverage=cfg.LEVERAGE,
                stop_buffer_pct=cfg.STOP_BUFFER_PCT,
            )
        except ValueError as e:
            log.error("Señal %s no dimensionable (%s); no se notifica", fired.direction, e)
            plan = None
        if plan is not None:
            log.info("SEÑAL %s — entrada=%.2f stop=%.2f size=%.6f BTC margen=%.2f USDT",
                     fired.direction.upper(), plan.entry, plan.stop, plan.size_btc, plan.margin_usdt)
            if on_signal:
                try:
                    on_signal(cfg, fired, plan)
                except Exception as e:  # noqa: BLE001
                    log.exception("on_signal falló: %s", e)

    state["last_candle_ts"] = candle_ts
    save_state(cfg.STATE_FILE, state)
    return True


def run_loop(cfg, state: dict,
             on_eval: Optional[OnEval] = None,
             on_signal: Optional[OnSignal] = None,
             stop_event=None) -> None:
    """Loop infinito. Nunca muere por un fallo puntual. `stop_event` (threading.Event)
    permite pararlo limpiamente si se usa desde el servidor."""
    log.info(
        "vigilancia activa | %s %s | poll=%ds | riesgo=%g USDT | lev=%dx",
        cfg.SYMBOL, cfg.TIMEFRAME, cfg.POLL_INTERVAL_SEC, cfg.RISK_USDT, cfg.LEVERAGE,
    )
    while stop_event is None or not stop_event.is_set():
        try:
            run_once(cfg, state, on_eval=on_eval, on_signal=on_signal)
        except Exception as e:  # noqa: BLE001 - el loop nunca debe morir
            log.exception("Error en el ciclo: %s", e)
        # sleep interrumpible
        if stop_event is not None:
            stop_event.wait(cfg.POLL_INTERVAL_SEC)
        else:
            time.sleep(cfg.POLL_INTERVAL_SEC)


def setup_logging() -> None:
    # journald (VPS) es UTF-8; la consola de Windows (cp1252) revienta con los
    # marcadores ✗/→/emoji. Forzamos UTF-8 en stdout para que loguee igual en ambos.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )


# ── Entrypoint standalone (solo Telegram) ─────────────────────────────
def main() -> None:
    setup_logging()
    cfg = Config
    once = "--once" in sys.argv
    dry = "--dry-run" in sys.argv or os.getenv("DRY_RUN", "").lower() in ("1", "true", "yes")

    notifier = Notifier(cfg.TELEGRAM_TOKEN, cfg.TELEGRAM_CHAT_ID, enabled=not dry)
    state = load_state(cfg.STATE_FILE)

    def on_signal(cfg, sig: Signal, plan) -> None:
        notifier.send(format_signal(sig, plan, cfg))

    log.info(
        "signal-watcher (standalone) | telegram=%s%s",
        "on" if cfg.telegram_enabled() else "off", " (DRY-RUN)" if dry else "",
    )

    if once:
        run_once(cfg, state, on_signal=on_signal)
        return
    run_loop(cfg, state, on_signal=on_signal)


if __name__ == "__main__":
    main()
