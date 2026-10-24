"""
J.A.R.V.I.S. — HUD Manager
The visual side of Jarvis: a notification center and a confirmation surface.

Two responsibilities:
  - Notifications: transient messages (a reminder fired, a task finished, a note
    from Eve) shown as glassmorphism toasts in the HUD overlay.
  - Confirmations: the "show me before you do it" safety gate. When a high-risk
    action needs approval, the HUD shows the drafted action with Approve/Decline
    buttons — a visual twin of the spoken consent prompt. Either the voice reply
    OR a button click resolves it.

State is read by the HUD overlay window via the control server (/api/hud).
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional

from loguru import logger


class HudManager:
    """Holds pending notifications and the active confirmation (singleton)."""

    def __init__(self, max_notifications: int = 20) -> None:
        self._lock = threading.Lock()
        self._notifications: Deque[Dict[str, Any]] = deque(maxlen=max_notifications)
        self._confirmation: Optional[Dict[str, Any]] = None
        self._next_id = 0
        # Set by the pipeline so a HUD button click can resolve the voice consent.
        self.on_confirm_response: Optional[Callable[[bool], None]] = None

    # ── Notifications ─────────────────────────────────────────────────────────
    def notify(self, title: str, body: str = "", level: str = "info") -> None:
        with self._lock:
            self._next_id += 1
            self._notifications.appendleft({
                "id": self._next_id,
                "title": title,
                "body": body,
                "level": level,  # info | success | warning
                "ts": time.time(),
            })
        logger.debug(f"[HUD] notify: {title}")

    # ── Confirmations (safety gate) ───────────────────────────────────────────
    def request_confirmation(self, description: str) -> None:
        """Show a confirmation card. Resolved by a button click or the voice gate."""
        with self._lock:
            self._next_id += 1
            self._confirmation = {"id": self._next_id, "text": description, "ts": time.time()}
        logger.info(f"[HUD] confirmation shown: {description}")

    def respond(self, approved: bool) -> None:
        """Called when the user clicks Approve/Decline in the HUD."""
        with self._lock:
            self._confirmation = None
        if self.on_confirm_response:
            try:
                self.on_confirm_response(approved)
            except Exception as e:
                logger.debug(f"[HUD] confirm response hook failed: {e}")

    def clear_confirmation(self) -> None:
        with self._lock:
            self._confirmation = None

    # ── Snapshot for the overlay ──────────────────────────────────────────────
    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            # Only surface notifications from the last 20 seconds (toasts fade).
            now = time.time()
            fresh: List[Dict[str, Any]] = [n for n in self._notifications if now - n["ts"] < 20]
            return {"confirmation": self._confirmation, "notifications": fresh}


# Process-wide singleton
hud_manager = HudManager()
