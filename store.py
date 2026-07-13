"""
Almacén ligero para el panel de la PWA: últimas señales disparadas y el estado
de la última evaluación (las 3 condiciones), en memoria + persistido a JSON.

No es la fuente de verdad del anti-spam (eso es state.json); esto es solo para
que la app pueda MOSTRAR qué está pasando.
"""

import json
import os
import threading
from collections import deque


class SignalStore:
    def __init__(self, path: str, maxlen: int = 50):
        self.path = path
        self._lock = threading.Lock()
        self.signals: deque = deque(maxlen=maxlen)
        self.last_eval: dict | None = None
        self._load()

    def _load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for s in data.get("signals", []):
                self.signals.append(s)
            self.last_eval = data.get("last_eval")
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _save(self) -> None:
        tmp = f"{self.path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"signals": list(self.signals), "last_eval": self.last_eval}, f)
        os.replace(tmp, self.path)

    def add_signal(self, signal: dict) -> None:
        with self._lock:
            self.signals.appendleft(signal)
            self._save()

    def set_eval(self, evaluation: dict) -> None:
        with self._lock:
            self.last_eval = evaluation
            self._save()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "last_eval": self.last_eval,
                "signals": list(self.signals),
            }
