/* signal-watcher PWA — registra el service worker, gestiona la suscripción de
   Web Push y pinta el panel (última evaluación + señales). */

let CONFIG = null;
let swReg = null;

const $ = (id) => document.getElementById(id);
const msg = (text, kind) => { const m = $('msg'); m.textContent = text || ''; m.className = 'msg ' + (kind || ''); };

function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(base64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

async function boot() {
  try {
    CONFIG = await (await fetch('/api/config')).json();
    $('app-name').textContent = CONFIG.appName || 'Signal Watcher';
    const syms = CONFIG.symbols || [];
    const tfs = CONFIG.timeframes || [];
    $('pair').textContent = `${syms.length} cripto · ${tfs.join(' + ')}`;
  } catch (e) { /* seguimos: el panel puede fallar sin romper la UI */ }

  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    $('sub-state').textContent = 'no soportado en este navegador';
    $('enable-btn').disabled = true;
    msg('Este navegador no soporta notificaciones push. En iPhone: añade la app a la pantalla de inicio y ábrela desde ahí.', 'err');
  } else {
    try {
      swReg = await navigator.serviceWorker.register('/sw.js');
      await refreshSubState();
    } catch (e) {
      msg('No se pudo registrar el service worker: ' + e.message, 'err');
    }
  }

  $('enable-btn').addEventListener('click', enablePush);
  $('test-btn').addEventListener('click', sendTest);
  refreshStatus();
  setInterval(refreshStatus, 30000);
}

async function refreshSubState() {
  const sub = swReg ? await swReg.pushManager.getSubscription() : null;
  const active = !!sub;
  $('sub-state').textContent = active ? 'activadas ✓' : 'desactivadas';
  $('sub-state').style.color = active ? 'var(--green)' : 'var(--muted)';
  $('enable-btn').textContent = active ? 'Avisos activados en este móvil' : 'Activar avisos en este móvil';
  $('enable-btn').disabled = active;
  return sub;
}

async function enablePush() {
  msg('');
  if (Notification.permission === 'denied') {
    msg('Has bloqueado las notificaciones para esta web. Actívalas en los ajustes del navegador.', 'err');
    return;
  }
  const perm = await Notification.requestPermission();
  if (perm !== 'granted') { msg('Permiso de notificaciones no concedido.', 'err'); return; }

  try {
    const sub = await swReg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(CONFIG.applicationServerKey),
    });
    const res = await fetch('/api/subscribe', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(sub),
    });
    if (!res.ok) throw new Error('el servidor rechazó la suscripción');
    await refreshSubState();
    msg('¡Listo! Recibirás un aviso cuando dispare una señal.', 'ok');
  } catch (e) {
    msg('No se pudo suscribir: ' + e.message, 'err');
  }
}

async function sendTest() {
  msg('Enviando prueba…');
  try {
    const res = await (await fetch('/api/test', { method: 'POST' })).json();
    if (res.sent > 0) msg(`Prueba enviada a ${res.sent} dispositivo(s). Debería llegarte en unos segundos.`, 'ok');
    else msg('No hay ningún dispositivo suscrito todavía. Pulsa "Activar avisos" primero.', 'err');
  } catch (e) { msg('Error enviando la prueba: ' + e.message, 'err'); }
}

function mark(v) { return v ? '<span class="mk y">✓</span>' : '<span class="mk n">✗</span>'; }

async function refreshStatus() {
  let s;
  try { s = await (await fetch('/api/status')).json(); } catch (e) { return; }
  $('live-dot').classList.add('on');

  // Última evaluación por SÍMBOLO × TIMEFRAME (dict {"SYM@tf": eval})
  const evals = s.last_eval || {};
  const syms = (CONFIG && CONFIG.symbols) || [];
  const tfs = (CONFIG && CONFIG.timeframes) || [];
  let keys = [];
  for (const sym of syms) for (const tf of tfs) keys.push(`${sym}@${tf}`);
  if (!keys.length) keys = Object.keys(evals);
  const rows = keys.filter((k) => evals[k]).map((k) => renderEval(evals[k]));
  if (rows.length) {
    $('eval').innerHTML = rows.join('');
  }

  // Señales (de cualquier símbolo, más recientes primero)
  const list = s.signals || [];
  if (list.length) {
    $('signals').innerHTML = list.map(renderSignal).join('');
  }
}

function renderEval(ev) {
  const asset = ev.base || ev.symbol;
  return `
    <div class="sig">
      <div class="top">
        <span><b>${asset}</b> <span class="tf">${ev.timeframe}</span></span>
        ${ev.fired ? `<span class="dir ${ev.fired}">${ev.fired.toUpperCase()}</span>` : ''}
        <span class="when">${fmt(ev.close)}</span>
      </div>
      <div class="conds">
        <span class="cond"><b>L</b> RSI ${mark(ev.long.rsi)} MACD ${mark(ev.long.macd)}</span>
        <span class="cond"><b>S</b> RSI ${mark(ev.short.rsi)} MACD ${mark(ev.short.macd)}</span>
      </div>
    </div>`;
}

function renderSignal(x) {
  const cls = x.direction === 'long' ? 'long' : 'short';
  return `
    <div class="sig">
      <div class="top">
        <span class="dir ${cls}">${x.direction.toUpperCase()}</span>
        <span>${x.symbol} ${x.timeframe}</span>
        <span class="when">${x.time_utc}</span>
      </div>
      <div class="grid">
        <div>Entrada <b>${fmt(x.entry)}</b></div><div>Stop ${fmt(x.stop)}</div>
        <div>Tamaño ${fmt(x.size_base)} ${x.base || ''}</div><div>Margen ${fmt(x.margin_usdt)} USDT</div>
        <div>1R ${fmt(x.risk_points)}</div><div>TP ${x.tps.map(fmt).join(' / ')}</div>
      </div>
    </div>`;
}

function fmt(n) {
  if (n === null || n === undefined) return '—';
  const x = Number(n);
  const ax = Math.abs(x);
  // Decimales según magnitud: con 2 fijos, DOGE/ADA/TRX salían como 0.
  const d = ax >= 100 ? 2 : ax >= 1 ? 4 : ax >= 0.01 ? 6 : 8;
  return x.toLocaleString('es-ES', { maximumFractionDigits: d });
}

boot();
