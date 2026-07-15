# crypto-signals (signal-watcher)

Servicio de **aviso** (no de ejecución) que vigila **las 10 cripto más fuertes en
Bitunix** (BTC, ETH, BNB, SOL, XRP, DOGE, ADA, TRX, AVAX, LINK — configurable),
evalúa en cada una una regla de **confluencia RSI + MACD** sobre **velas
cerradas** (en **1h y 4h** a la vez), y avisa por **Web Push a una PWA
instalable en el móvil** cuando se cumplen las dos, incluyendo tamaño de
posición y niveles R. La ruptura de nivel de precio se muestra como dato
informativo pero **no se exige** para disparar.

> **No pone órdenes. Solo detecta y notifica.**
> **Los avisos van SOLO al móvil (Web Push). No usa Telegram.**

La lista de pares se controla con la env var `SYMBOLS` (separada por comas). El
motor evalúa cada símbolo de forma independiente en cada ciclo, con indicadores,
niveles y estado anti-repintado propios por par.

---

## La regla (confluencia RSI + MACD sobre velas cerradas)

Los **cruces** de RSI y MACD valen si ocurrieron en cualquiera de las últimas
`CONFLUENCE_WINDOW` velas (por defecto **5**, incluida la actual).

**LONG**
1. **RSI** cruzó al alza el nivel 30 en las últimas W velas.
2. **MACD** histograma cruzó de negativo a positivo en las últimas W velas
   (opcional: línea MACD > señal en la vela actual, `MACD_REQUIRE_ABOVE_SIGNAL=true`).

**SHORT** (simétrica)
1. **RSI** cruzó a la baja el 70 en las últimas W velas.
2. **MACD** histograma cruzó de positivo a negativo en las últimas W velas.

Regla dura: **una condición sola no es señal.** El estado (incluida la ruptura
de nivel, ya solo informativa) se loguea en cada vela aunque no dispare.

> ¿Por qué la ventana? Con `CONFLUENCE_WINDOW=1` (todo en la MISMA vela), un
> backtest de 4 meses en 1h sobre los 10 pares por defecto dio **0 señales**:
> los eventos son puntuales y casi nunca coinciden en la misma vela. Con **5**
> salieron ~20 señales (≈1/semana entre los 10 pares), aún exigiendo también la
> ruptura de nivel; sin exigirla habrá bastantes más.

### Niveles (v1, simple a propósito)
Swing high/low de las últimas `N` velas, excluyendo la vela que dispara:
`resistencia = max(high[-N:-1])`, `soporte = min(low[-N:-1])`. Está aislado en
[`levels.py`](levels.py) para mejorarlo luego sin tocar el resto.

---

## Qué calcula al disparar (lógica R)

- **Entrada** = cierre de la vela que disparó.
- **Stop** = al otro lado del nivel roto, con buffer (`STOP_BUFFER_PCT`, p.ej. 0.1%):
  long → bajo el **soporte** swing; short → sobre la **resistencia**.
- **1R** = `abs(entrada − stop)` (puntos de precio).
- **Tamaño (BTC)** = `RISK_USDT / 1R`. El **apalancamiento NO cambia el riesgo**,
  solo el **margen** (`= tamaño × entrada / apalancamiento`).
- **TP1/TP2/TP3** = entrada ± 1R·{1,2,3} según dirección.
- **Break-even**: recordatorio de subir el stop a la entrada en +1R.

---

## Fuente de datos (Bitunix, klines)

Endpoint público (sin firma), confirmado en vivo:

```
GET https://fapi.bitunix.com/api/v1/futures/market/kline?symbol=BTCUSDT&interval=1h&limit=200
```

Cada vela: `{open, high, low, close, quoteVol, baseVol, time}` (valores string;
`time` = open-time en ms). La API devuelve la lista **descendente** (la más nueva
primero) y suele incluir la vela **en formación**. `signal-watcher`:

- ordena **ascendente**;
- **descarta la vela en formación** deduciendo el cierre de `open_time + interval <= now`
  (anti-repintado robusto);
- guarda el `open_time` de la última vela procesada en `STATE_FILE` para **no
  re-evaluar ni re-notificar** la misma vela (ni siquiera tras un reinicio).

Los indicadores (RSI, MACD) se calculan **en local** con la librería `ta` a través
de [`pandas_ta_compat.py`](pandas_ta_compat.py) (el mismo shim que el crypto-agent).
No se confía en indicadores del exchange.

---

## Arquitectura

| Módulo | Responsabilidad |
|---|---|
| [`config.py`](config.py) | Config por env vars / `.env`. |
| [`data.py`](data.py) | Klines Bitunix + lógica de vela cerrada. |
| [`indicators.py`](indicators.py) | RSI + MACD (sobre `ta`). |
| [`levels.py`](levels.py) | Soporte/resistencia (swing high/low). |
| [`rules.py`](rules.py) | Evalúa las 3 condiciones → objeto `Signal` estructurado. |
| [`sizing.py`](sizing.py) | Lógica R. |
| [`notify.py`](notify.py) | Formato del mensaje (+ Telegram opcional solo en modo standalone). |
| [`main.py`](main.py) | Loop de sondeo multi-par + estado por símbolo (fan-out por callbacks). |
| [`server.py`](server.py) | **Servidor de la PWA + Web Push**; corre el loop en un hilo. |
| [`webpush.py`](webpush.py) | Claves VAPID + suscripciones + envío de push. |
| [`store.py`](store.py) | Últimas señales + última evaluación (para el panel). |
| [`static/`](static/) | PWA: `index.html`, `app.js`, `sw.js`, manifest, iconos. |

`rules.py` devuelve un `Signal` con dirección, precio y el estado booleano de cada
condición. Para añadir una condición (p.ej. **divergencias RSI**) basta con
implementar su check, rellenar `Conditions.divergence` y `all_pass` la tendrá en
cuenta — sin tocar sizing/notify/main.

---

## Uso

```bash
python -m venv .venv && source .venv/bin/activate   # (Windows: .venv\Scripts\activate)
pip install -r requirements.txt
cp .env.example .env        # rellena TELEGRAM_TOKEN/CHAT_ID (opcional) y VAPID_SUBJECT
python make_icons.py        # genera los iconos de la PWA (una vez)

# Opción A — servidor con PWA + Web Push + loop (recomendado, sin Telegram):
python server.py            # sirve en http://localhost:8095

# Opción B — solo motor por consola (Telegram opcional si rellenas el .env), sin PWA:
python main.py --once --dry-run   # un ciclo sobre los 10 pares, sin enviar (para probar)
python main.py                    # loop
```

`main.py` flags: `--once` (un ciclo y salir), `--dry-run` (no envía; también `DRY_RUN=true`).

---

## PWA: avisos al móvil (Web Push)

La PWA se instala en la pantalla de inicio y te llega un **aviso nativo** cuando
dispara una señal, aunque no tengas la app abierta. Es **aditivo al Telegram**.

**Requisito clave:** el navegador solo permite notificaciones push en **contexto
seguro** → `https://` (o `localhost` para pruebas). Para el móvil necesitas una
**URL HTTPS** que apunte a este servidor.

### 1) Probar en el ordenador (sin HTTPS, en 1 minuto)
```bash
python server.py
```
Abre `http://localhost:8095` en Chrome/Edge de escritorio → **Activar avisos** →
**Enviar aviso de prueba**. `localhost` cuenta como contexto seguro, así validas
todo el circuito antes de tocar el VPS.

### 2) Ponerlo en el móvil (elige una vía para el HTTPS)

**Vía A — dominio + Caddy (HTTPS automático) en tu VPS Hetzner.** Si tienes (o
registras) un dominio apuntando a la IP del VPS:
```
# /etc/caddy/Caddyfile
signals.tudominio.com {
    reverse_proxy localhost:8095
}
```
`sudo systemctl reload caddy` — Caddy saca el certificado Let's Encrypt solo.
En el móvil abre `https://signals.tudominio.com`.

**Vía B — Cloudflare Tunnel (sin abrir puertos ni dominio propio).**
```
cloudflared tunnel --url http://localhost:8095
```
Te da una URL `https://xxxx.trycloudflare.com` lista para el móvil (para algo
permanente, crea un named tunnel con tu dominio en Cloudflare).

### 3) Instalar y activar en el móvil
- **Android/Chrome:** abre la URL HTTPS → menú ⋮ → *Añadir a pantalla de inicio* →
  abre el icono → **Activar avisos** → *Permitir*.
- **iPhone (iOS 16.4+):** Safari → *Compartir* → **Añadir a pantalla de inicio**
  (⚠️ **obligatorio**: en iOS el push web **solo** funciona desde la app instalada,
  no desde la pestaña de Safari) → abre el icono → **Activar avisos** → *Permitir*.

Pulsa **Enviar aviso de prueba** para confirmar. A partir de ahí, cada señal llega
sola. Cada dispositivo se suscribe una vez; se guardan en `subscriptions.json`.

> Las claves **VAPID** se autogeneran en `vapid_private.pem` al primer arranque.
> No lo borres (invalidaría las suscripciones) ni lo subas a git (ya está en
> `.gitignore` junto a `.env` y los `.json` de estado).

---

## Despliegue systemd (como el crypto-agent)

```bash
sudo cp -r . /opt/signal-watcher
sudo cp signal-watcher.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now signal-watcher
journalctl -u signal-watcher -f      # logs (estado de las 3 condiciones por vela)
```
El `.service` arranca `server.py` (PWA + push + loop). Ponlo detrás de Caddy/Cloudflare
para el HTTPS. Para modo solo-Telegram sin PWA, cambia el `ExecStart` a `main.py`.

---

## Fuera de v1 (preparado, no implementado)

- **Divergencias RSI** (4ª condición): interfaz lista en `rules.py`, sin implementar.
- **Ejecución de órdenes**.
- **Multi-timeframe** (multi-par ya implementado vía `SYMBOLS`).

---

## Aviso

MACD y RSI son indicadores de **momentum**: generan **señales falsas en mercado
lateral**. Esta herramienta **avisa, no decide**; el filtro de **nivel de precio**
existe precisamente para recortar las falsas de rango. **No es consejo financiero.**
