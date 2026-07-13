"""
Notificación por Telegram (bot de salida). Mismo enfoque que alertas.py del
crypto-agent: HTTP directo con urllib + parse_mode HTML, sin dependencias extra.
"""

import json
import urllib.request
from datetime import datetime, timezone

from rules import Signal
from sizing import RiskPlan


class Notifier:
    def __init__(self, token: str, chat_id: str, enabled: bool = True):
        self.token = token
        self.chat_id = chat_id
        self.enabled = enabled and bool(token and chat_id)

    def send(self, text: str) -> bool:
        if not self.enabled:
            print("  [notify] Telegram desactivado (sin token/chat_id); mensaje no enviado")
            return False
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            data = json.dumps({
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
            }).encode()
            req = urllib.request.Request(
                url, data=data, headers={"Content-Type": "application/json"}
            )
            urllib.request.urlopen(req, timeout=10)
            return True
        except Exception as e:  # noqa: BLE001
            print(f"  [notify] Telegram error: {e}")
            return False


def _fmt_px(x: float) -> str:
    return f"{x:,.2f}"


def base_asset(symbol: str) -> str:
    """'BTCUSDT' -> 'BTC', 'ETHUSDT' -> 'ETH'. Fallback: el propio símbolo."""
    for quote in ("USDT", "USDC", "USD"):
        if symbol.upper().endswith(quote):
            return symbol[: -len(quote)]
    return symbol


def format_signal(symbol: str, timeframe: str, sig: Signal, plan: RiskPlan, cfg) -> str:
    icon = "📈" if sig.direction == "long" else "📉"
    asset = base_asset(symbol)
    when = datetime.fromtimestamp(sig.candle_ts / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if sig.direction == "long":
        rsi_line = f"RSI cruce ↑ {cfg.RSI_LONG_LEVEL:g}   ({sig.rsi_prev:.1f} → {sig.rsi_curr:.1f})"
        macd_line = f"MACD hist −→+   ({sig.hist_prev:+.2f} → {sig.hist_curr:+.2f})"
        price_line = f"Cierre > resistencia {_fmt_px(sig.resistance)}"
        stop_note = f"bajo soporte swing {_fmt_px(plan.level_broken)}, buffer {cfg.STOP_BUFFER_PCT*100:g}%"
    else:
        rsi_line = f"RSI cruce ↓ {cfg.RSI_SHORT_LEVEL:g}   ({sig.rsi_prev:.1f} → {sig.rsi_curr:.1f})"
        macd_line = f"MACD hist +→−   ({sig.hist_prev:+.2f} → {sig.hist_curr:+.2f})"
        price_line = f"Cierre < soporte {_fmt_px(sig.support)}"
        stop_note = f"sobre resistencia swing {_fmt_px(plan.level_broken)}, buffer {cfg.STOP_BUFFER_PCT*100:g}%"

    tp1, tp2, tp3 = plan.tps
    lines = [
        f"{icon} <b>SEÑAL {sig.direction.upper()} — {symbol} ({timeframe})</b>",
        f"Vela cerrada: {when}",
        "",
        f"Entrada:  <b>{_fmt_px(plan.entry)}</b>",
        f"Stop:     {_fmt_px(plan.stop)}  ({stop_note})",
        f"1R:       {plan.risk_points:,.2f} pts",
        "",
        f"Tamaño:   <b>{plan.size_base:.6f} {asset}</b>   (riesgo {plan.risk_usdt:g} USDT)",
        f"Margen:   {plan.margin_usdt:,.2f} USDT   ({plan.leverage}x — el apalancamiento NO cambia el riesgo)",
        "",
        f"TP1 (1R): {_fmt_px(tp1)}",
        f"TP2 (2R): {_fmt_px(tp2)}",
        f"TP3 (3R): {_fmt_px(tp3)}",
        f"⏫ Break-even: sube el stop a {_fmt_px(plan.breakeven)} al llegar a +1R",
        "",
        "<b>Condiciones (3/3):</b>",
        f"✅ {rsi_line}",
        f"✅ {macd_line}",
        f"✅ {price_line}",
    ]
    return "\n".join(lines)
