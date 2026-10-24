"""
J.A.R.V.I.S. — UI State Bridge
A tiny thread-safe holder for Jarvis's current state (idle / listening /
thinking / speaking) plus the latest spoken/heard text. The orb and dashboard
read this (via the control server) to stay in sync with what Jarvis is doing.
"""
from __future__ import annotations

import threading
import time
from typing import Dict


class StateBridge:
    """Current UI state, updated by the pipeline and read by the UI (singleton)."""

    VALID = {"idle", "listening", "thinking", "speaking"}

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = "idle"
        self._text = ""
        self._ts = time.time()

    def set(self, state: str, text: str = "") -> None:
        if state not in self.VALID:
            state = "idle"
        with self._lock:
            self._state = state
            if text:
                self._text = text[:300]
            self._ts = time.time()

    def set_text(self, text: str) -> None:
        with self._lock:
            self._text = (text or "")[:300]
            self._ts = time.time()

    def snapshot(self) -> Dict:
        with self._lock:
            return {"state": self._state, "text": self._text, "ts": self._ts}


# Process-wide singleton
state_bridge = StateBridge()
