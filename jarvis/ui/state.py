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


class UIDirective:
    """
    Out-of-band UI commands for the Dynamic Island (singleton).

    Voice/tools push a desired mode ('collapsed' | 'mini' | 'tools' | 'dashboard')
    and/or a z-order hint ('forward'). The island process polls a monotonically
    increasing `seq` and only *acts* when it changes, so a repeated "open
    dashboard" re-triggers even if the mode is unchanged. The island also sends
    a heartbeat so callers can tell whether it's actually running.
    """

    MODES = {"collapsed", "mini", "tools", "dashboard"}

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._mode = "collapsed"
        self._forward = False
        self._seq = 0
        self._last_beat = 0.0

    def set(self, mode: str | None = None, forward: bool | None = None) -> None:
        with self._lock:
            if mode in self.MODES:
                self._mode = mode
            if forward is not None:
                self._forward = bool(forward)
            self._seq += 1

    def heartbeat(self) -> None:
        with self._lock:
            self._last_beat = time.time()

    def is_alive(self, within: float = 4.0) -> bool:
        with self._lock:
            return (time.time() - self._last_beat) < within

    def snapshot(self) -> Dict:
        with self._lock:
            return {"mode": self._mode, "forward": self._forward, "seq": self._seq}


ui_directive = UIDirective()
