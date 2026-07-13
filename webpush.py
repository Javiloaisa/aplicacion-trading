"""
Web Push (VAPID + aes128gcm) para la PWA. Usa pywebpush + py_vapid.

Responsabilidades:
  - Autogenerar el par de claves VAPID la primera vez (vapid_private.pem).
  - Exponer la "application server key" (base64url) que el navegador necesita
    para suscribirse.
  - Guardar/quitar suscripciones (subscriptions.json).
  - Enviar una notificación a TODAS las suscripciones y podar las muertas (404/410).

No requiere HTTPS para funcionar el código, pero el NAVEGADOR sí exige contexto
seguro (https:// o localhost) para registrar el service worker y suscribirse.
"""

import base64
import json
import logging
import os
import threading

from py_vapid import Vapid01
from pywebpush import webpush, WebPushException
from cryptography.hazmat.primitives import serialization

log = logging.getLogger("signal-watcher.push")


class PushManager:
    def __init__(self, cfg):
        self.cfg = cfg
        self.priv_file = cfg.VAPID_PRIVATE_KEY_FILE
        self.subs_file = cfg.SUBSCRIPTIONS_FILE
        self.subject = cfg.VAPID_SUBJECT
        self._lock = threading.Lock()

        self._ensure_keys()
        self.application_server_key = self._compute_app_server_key()
        self.subs = self._load_subs()
        log.info("PushManager listo | %d suscripción(es) | appServerKey=%s…",
                 len(self.subs), self.application_server_key[:12])

    # ── Claves VAPID ──────────────────────────────────────────
    def _ensure_keys(self) -> None:
        if not os.path.exists(self.priv_file):
            v = Vapid01()
            v.generate_keys()
            v.save_key(self.priv_file)
            log.info("Generado nuevo par de claves VAPID en %s", self.priv_file)

    def _compute_app_server_key(self) -> str:
        """Clave pública en punto sin comprimir, base64url sin padding (la que
        el cliente pasa como applicationServerKey a pushManager.subscribe)."""
        v = Vapid01.from_file(self.priv_file)
        raw = v.public_key.public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint,
        )
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    # ── Suscripciones ─────────────────────────────────────────
    def _load_subs(self) -> list:
        try:
            with open(self.subs_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _save_subs(self) -> None:
        tmp = f"{self.subs_file}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.subs, f)
        os.replace(tmp, self.subs_file)

    @staticmethod
    def _endpoint(sub: dict) -> str:
        return (sub or {}).get("endpoint", "")

    def add_subscription(self, sub: dict) -> bool:
        """Guarda (o refresca) una suscripción. Dedup por endpoint."""
        ep = self._endpoint(sub)
        if not ep or "keys" not in sub:
            raise ValueError("suscripción inválida (falta endpoint o keys)")
        with self._lock:
            self.subs = [s for s in self.subs if self._endpoint(s) != ep]
            self.subs.append(sub)
            self._save_subs()
        log.info("Nueva suscripción (%d en total)", len(self.subs))
        return True

    def remove_subscription(self, endpoint: str) -> bool:
        with self._lock:
            before = len(self.subs)
            self.subs = [s for s in self.subs if self._endpoint(s) != endpoint]
            if len(self.subs) != before:
                self._save_subs()
                return True
        return False

    def count(self) -> int:
        return len(self.subs)

    # ── Envío ─────────────────────────────────────────────────
    def send_to_all(self, payload: dict, ttl: int = 3600) -> dict:
        """Envía `payload` (dict JSON) a todas las suscripciones. Poda las muertas."""
        with self._lock:
            targets = list(self.subs)
        data = json.dumps(payload)
        dead, sent = [], 0
        for sub in targets:
            try:
                webpush(
                    subscription_info=sub,
                    data=data,
                    vapid_private_key=self.priv_file,
                    vapid_claims={"sub": self.subject},
                    ttl=ttl,
                )
                sent += 1
            except WebPushException as e:
                code = getattr(getattr(e, "response", None), "status_code", None)
                if code in (404, 410):
                    dead.append(self._endpoint(sub))   # suscripción caducada/cancelada
                else:
                    log.warning("Push fallido (%s): %s", code, e)
            except Exception as e:  # noqa: BLE001
                log.warning("Push error inesperado: %s", e)

        if dead:
            with self._lock:
                self.subs = [s for s in self.subs if self._endpoint(s) not in dead]
                self._save_subs()
        result = {"sent": sent, "removed": len(dead), "total": len(self.subs)}
        log.info("Push enviado: %s", result)
        return result
