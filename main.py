"""
signal-watcher — motor de vigilancia (loop).

Cada POLL_INTERVAL_SEC: baja velas, comprueba si hay una vela CERRADA nueva,
calcula indicadores + niveles, evalúa la regla de 3 condiciones y, si dispara,
avisa. NO ejecuta órdenes.

El envío del aviso NO vive aquí: run_once/run_loop reciben callbacks
(on_eval, on_signal) y el que llama decide dónde va el aviso:
  - main() (este fichero, standalone)  -> solo Telegram.
  - server.py                          -> Telegram + Web Push (PWA) + panel.

Multi-par: vigila TODOS los símbolos de cfg.SYMBOLS en cada ciclo (misma regla en
cada uno, indicadores y niveles independientes).

Anti-repintado + anti-spam:
  - Solo se evalúa la última vela cerrada (data.drop_unclosed).
  - Se guarda el open_time de la última vela procesada POR SÍMBOLO en STATE_FILE;
    una vela ya procesada no se re-evalúa ni re-notifica (incluso tras un reinicio).

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

# Firmas de los callbacks (incluyen el símbolo, porque el motor es multi-par):
#   on_eval(cfg, symbol:str, candle_ts:int, close:float, levels:Levels, ev:Evaluation) -> None
#   on_signal(cfg, symbol:str, sig:Signal, plan:RiskPlan) -> None
OnEval   = Callable[[Config, str, int, float, Levels, Evaluation], None]
OnSignal = Callable[[Config, str, Signal, object], None]


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


# ── Un ciclo, UN símbolo ──────────────────────────────────────────────
def run_once(cfg, symbol: str, state: dict,
             on_eval: Optional[OnEval] = None,
             on_signal: Optional[OnSignal] = None) -> bool:
    """
    Procesa como mucho una vela nueva de `symbol`. Devuelve True si había vela nueva
    (y por tanto se actualizó el estado), False si no había nada nuevo.

    El estado es por símbolo: state["last_ts"][symbol] = open_time de la última vela
    procesada, para no re-evaluar ni re-notificar la misma vela (ni tras un reinicio).
    """
    last_ts = state.setdefault("last_ts", {})

    df = kdata.fetch_klines(symbol, cfg.TIMEFRAME, cfg.KLINES_LIMIT, cfg.BASE_URL)
    df = kdata.drop_unclosed(df, cfg.TIMEFRAME)

    min_rows = max(cfg.SWING_N, cfg.MACD_SLOW + cfg.MACD_SIGNAL, cfg.RSI_PERIOD) + 2
    if len(df) < min_rows:
        log.warning("[%s] Pocas velas cerradas (%d < %d); espero al siguiente ciclo",
                    symbol, len(df), min_rows)
        return False

    candle_ts = kdata.last_closed_ts(df)
    if last_ts.get(symbol) == candle_ts:
        return False   # esta vela ya se procesó (nada nuevo)

    df = add_indicators(df, cfg)
    if not has_warmup(df):
        log.warning("[%s] Indicadores con NaN en las últimas velas; espero más historia", symbol)
        return False

    levels = swing_levels(df, cfg.SWING_N)
    ev = evaluate(df, levels, cfg)

    when = datetime.fromtimestamp(candle_ts / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")
    close = float(df["close"].iloc[-1])
    fired = ev.fired
    verdict = f"→ FIRED {fired.direction.upper()}" if fired else "→ sin señal"
    log.info(
        "[%s UTC] %s %s close=%.2f | res=%.2f sop=%.2f | LONG %s | SHORT %s %s",
        when, symbol, cfg.TIMEFRAME, close,
        levels.resistance, levels.support,
        ev.long.conditions.as_marks(), ev.short.conditions.as_marks(), verdict,
    )

    if on_eval:
        try:
            on_eval(cfg, symbol, candle_ts, close, levels, ev)
        except Exception as e:  # noqa: BLE001 - un fallo de panel no debe cortar el loop
            log.exception("on_eval falló (%s): %s", symbol, e)

    if fired:
        try:
            plan = build_plan(
                fired,
                risk_usdt=cfg.RISK_USDT,
                leverage=cfg.LEVERAGE,
                stop_buffer_pct=cfg.STOP_BUFFER_PCT,
            )
        except ValueError as e:
            log.error("[%s] Señal %s no dimensionable (%s); no se notifica",
                      symbol, fired.direction, e)
            plan = None
        if plan is not None:
            log.info("SEÑAL %s %s — entrada=%.2f stop=%.2f size=%.6f margen=%.2f USDT",
                     symbol, fired.direction.upper(), plan.entry, plan.stop,
                     plan.size_base, plan.margin_usdt)
            if on_signal:
                try:
                    on_signal(cfg, symbol, fired, plan)
                except Exception as e:  # noqa: BLE001
                    log.exception("on_signal falló (%s): %s", symbol, e)

    last_ts[symbol] = candle_ts
    save_state(cfg.STATE_FILE, state)
    return True


# ── Un ciclo, TODOS los símbolos ──────────────────────────────────────
def run_cycle(cfg, state: dict,
              on_eval: Optional[OnEval] = None,
              on_signal: Optional[OnSignal] = None) -> None:
    """Recorre cfg.SYMBOLS. Un fallo en un símbolo no afecta a los demás."""
    for symbol in cfg.SYMBOLS:
        try:
            run_once(cfg, symbol, state, on_eval=on_eval, on_signal=on_signal)
        except Exception as e:  # noqa: BLE001 - aislar el fallo por símbolo
            log.exception("[%s] Error en el ciclo: %s", symbol, e)


def run_loop(cfg, state: dict,
             on_eval: Optional[OnEval] = None,
             on_signal: Optional[OnSignal] = None,
             stop_event=None) -> None:
    """Loop infinito. Nunca muere por un fallo puntual. `stop_event` (threading.Event)
    permite pararlo limpiamente si se usa desde el servidor."""
    log.info(
        "vigilancia activa | %d símbolos: %s | %s | poll=%ds | riesgo=%g USDT | lev=%dx",
        len(cfg.SYMBOLS), ", ".join(cfg.SYMBOLS), cfg.TIMEFRAME,
        cfg.POLL_INTERVAL_SEC, cfg.RISK_USDT, cfg.LEVERAGE,
    )
    while stop_event is None or not stop_event.is_set():
        try:
            run_cycle(cfg, state, on_eval=on_eval, on_signal=on_signal)
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

    def on_signal(cfg, symbol: str, sig: Signal, plan) -> None:
        notifier.send(format_signal(symbol, sig, plan, cfg))

    log.info(
        "signal-watcher (standalone) | %d símbolos | telegram=%s%s",
        len(cfg.SYMBOLS), "on" if cfg.telegram_enabled() else "off",
        " (DRY-RUN)" if dry else "",
    )

    if once:
        run_cycle(cfg, state, on_signal=on_signal)
        return
    run_loop(cfg, state, on_signal=on_signal)


if __name__ == "__main__":
    main()
