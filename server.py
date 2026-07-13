"""
signal-watcher — servidor de la PWA + Web Push.

Un solo proceso:
  - Sirve la PWA (static/) y su manifest/service-worker.
  - Gestiona las suscripciones de notificaciones (/api/subscribe).
  - Corre el motor de vigilancia (main.run_loop) en un hilo de fondo.
  - Cuando una señal dispara -> Telegram + Web Push (a todos los móviles) + panel.

Arranque:  python server.py
Local (para probar sin HTTPS):  abre http://localhost:8095 en Chrome de escritorio
(localhost cuenta como contexto seguro). Para el MÓVIL necesitas HTTPS (ver README).
"""

import logging
import os
import threading
from datetime import datetime, timezone

from flask import Flask, jsonify, request, send_from_directory

from config import Config
import main as engine
from notify import Notifier, format_signal
from webpush import PushManager
from store import SignalStore

log = logging.getLogger("signal-watcher.server")

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")

# ── Componentes compartidos ───────────────────────────────────────────
_dry = os.getenv("DRY_RUN", "").lower() in ("1", "true", "yes")
push = PushManager(Config)
store = SignalStore(Config.SIGNALS_FILE)
notifier = Notifier(Config.TELEGRAM_TOKEN, Config.TELEGRAM_CHAT_ID, enabled=not _dry)

_watcher_started = False
_watcher_lock = threading.Lock()


# ── Serialización para panel / push ───────────────────────────────────
def _iso(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _signal_record(cfg, sig, plan) -> dict:
    return {
        "ts": sig.candle_ts,
        "time_utc": _iso(sig.candle_ts),
        "symbol": cfg.SYMBOL,
        "timeframe": cfg.TIMEFRAME,
        "direction": sig.direction,
        "entry": round(plan.entry, 2),
        "stop": round(plan.stop, 2),
        "risk_points": round(plan.risk_points, 2),
        "size_btc": round(plan.size_btc, 6),
        "notional_usdt": round(plan.notional_usdt, 2),
        "margin_usdt": round(plan.margin_usdt, 2),
        "leverage": plan.leverage,
        "risk_usdt": plan.risk_usdt,
        "tps": [round(t, 2) for t in plan.tps],
        "resistance": round(sig.resistance, 2),
        "support": round(sig.support, 2),
        "rsi": [round(sig.rsi_prev, 1), round(sig.rsi_curr, 1)],
        "hist": [round(sig.hist_prev, 2), round(sig.hist_curr, 2)],
    }


def _push_payload(rec: dict) -> dict:
    icon = "📈" if rec["direction"] == "long" else "📉"
    body = (f"Entrada {rec['entry']:,.2f} · Stop {rec['stop']:,.2f} · "
            f"{rec['size_btc']:.6f} BTC · TP1 {rec['tps'][0]:,.2f}")
    return {
        "title": f"{icon} SEÑAL {rec['direction'].upper()} — {rec['symbol']} ({rec['timeframe']})",
        "body": body,
        "tag": f"{rec['symbol']}-{rec['ts']}-{rec['direction']}",
        "url": "/",
    }


# ── Callbacks del motor ───────────────────────────────────────────────
def on_eval(cfg, candle_ts, close, levels, ev) -> None:
    store.set_eval({
        "ts": candle_ts,
        "time_utc": _iso(candle_ts),
        "symbol": cfg.SYMBOL,
        "timeframe": cfg.TIMEFRAME,
        "close": round(close, 2),
        "resistance": round(levels.resistance, 2),
        "support": round(levels.support, 2),
        "long": {"rsi": ev.long.conditions.rsi, "macd": ev.long.conditions.macd,
                 "price": ev.long.conditions.price},
        "short": {"rsi": ev.short.conditions.rsi, "macd": ev.short.conditions.macd,
                  "price": ev.short.conditions.price},
        "fired": ev.fired.direction if ev.fired else None,
    })


def on_signal(cfg, sig, plan) -> None:
    rec = _signal_record(cfg, sig, plan)
    store.add_signal(rec)
    # Telegram (si está configurado)
    notifier.send(format_signal(sig, plan, cfg))
    # Web Push a los móviles (PWA)
    if cfg.PUSH_ENABLED:
        push.send_to_all(_push_payload(rec))


# ── Hilo de vigilancia ────────────────────────────────────────────────
def start_watcher() -> None:
    global _watcher_started
    with _watcher_lock:
        if _watcher_started:
            return
        _watcher_started = True
    state = engine.load_state(Config.STATE_FILE)

    def _run():
        engine.run_loop(Config, state, on_eval=on_eval, on_signal=on_signal)

    threading.Thread(target=_run, name="watcher", daemon=True).start()
    log.info("Hilo de vigilancia lanzado")


# ── Rutas: PWA ────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/sw.js")
def service_worker():
    # Se sirve en la raíz para que el scope del service worker sea "/".
    resp = send_from_directory(STATIC_DIR, "sw.js")
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Content-Type"] = "application/javascript"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/manifest.webmanifest")
def manifest():
    resp = send_from_directory(STATIC_DIR, "manifest.webmanifest")
    resp.headers["Content-Type"] = "application/manifest+json"
    return resp


# ── Rutas: API ────────────────────────────────────────────────────────
@app.route("/api/config")
def api_config():
    return jsonify({
        "appName": Config.APP_NAME,
        "symbol": Config.SYMBOL,
        "timeframe": Config.TIMEFRAME,
        "applicationServerKey": push.application_server_key,
        "pushEnabled": Config.PUSH_ENABLED,
    })


@app.route("/api/subscribe", methods=["POST"])
def api_subscribe():
    sub = request.get_json(silent=True)
    try:
        push.add_subscription(sub)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "subscriptions": push.count()})


@app.route("/api/unsubscribe", methods=["POST"])
def api_unsubscribe():
    body = request.get_json(silent=True) or {}
    endpoint = body.get("endpoint", "")
    removed = push.remove_subscription(endpoint)
    return jsonify({"ok": True, "removed": removed, "subscriptions": push.count()})


@app.route("/api/status")
def api_status():
    snap = store.snapshot()
    return jsonify({
        "appName": Config.APP_NAME,
        "symbol": Config.SYMBOL,
        "timeframe": Config.TIMEFRAME,
        "subscriptions": push.count(),
        "telegram": Config.telegram_enabled(),
        "pushEnabled": Config.PUSH_ENABLED,
        **snap,
    })


@app.route("/api/test", methods=["POST"])
def api_test():
    result = push.send_to_all({
        "title": f"🔔 {Config.APP_NAME}",
        "body": f"Prueba de aviso · {Config.SYMBOL} {Config.TIMEFRAME}. Si ves esto, el push funciona.",
        "tag": "test",
        "url": "/",
    })
    return jsonify({"ok": True, **result})


# ── Arranque ──────────────────────────────────────────────────────────
def _serve() -> None:
    engine.setup_logging()
    log.info("%s | http://%s:%d | símbolo=%s %s | push=%s telegram=%s%s",
             Config.APP_NAME, Config.WEB_HOST, Config.WEB_PORT, Config.SYMBOL, Config.TIMEFRAME,
             "on" if Config.PUSH_ENABLED else "off",
             "on" if Config.telegram_enabled() else "off",
             " (DRY-RUN)" if _dry else "")
    start_watcher()
    try:
        from waitress import serve  # servidor WSGI de producción (opcional)
        log.info("Sirviendo con waitress")
        serve(app, host=Config.WEB_HOST, port=Config.WEB_PORT)
    except ImportError:
        log.info("waitress no instalado; usando el servidor de Flask (threaded)")
        app.run(host=Config.WEB_HOST, port=Config.WEB_PORT, threaded=True, use_reloader=False)


if __name__ == "__main__":
    _serve()
