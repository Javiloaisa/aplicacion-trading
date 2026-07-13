"""
Almacén ligero para el panel de la PWA: últimas señales disparadas y el estado
de la última evaluación (las 3 condiciones) POR SÍMBOLO, en memoria + persistido
a JSON.

No es la fuente de verdad del anti-spam (eso es state.json); esto es solo para
que la app pueda MOSTRAR qué está pasando.
"""

import json
import os
import threading
from collections import deque


class SignalStore:
    def __init__(self, path: str, maxlen: int = 100):
        self.path = path
        self._lock = threading.Lock()
        self.signals: deque = deque(maxlen=maxlen)
        # Última evaluación por símbolo: {"BTCUSDT": {...}, "ETHUSDT": {...}, …}
        self.last_eval: dict = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for s in data.get("signals", []):
                self.signals.append(s)
            ev = data.get("last_eval")
            # Compat: formato antiguo (una sola evaluación, no dict por símbolo).
            if isinstance(ev, dict) and ("long" in ev or "short" in ev):
                sym = ev.get("symbol")
                self.last_eval = {sym: ev} if sym else {}
            elif isinstance(ev, dict):
                self.last_eval = ev
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

    def set_eval(self, symbol: str, evaluation: dict) -> None:
        with self._lock:
            self.last_eval[symbol] = evaluation
            self._save()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "last_eval": self.last_eval,
                "signals": list(self.signals),
            }
