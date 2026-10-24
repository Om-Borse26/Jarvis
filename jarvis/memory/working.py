"""
J.A.R.V.I.S. — L2 Working Memory
Fast, in-RAM state for the CURRENT moment: what app is focused, what's on screen,
the clipboard, the active task, and the most recent tool results.

This is volatile by design (it reflects "now"), and is injected as short context
into the LLM prompt so Jarvis stays aware of the live situation and of what it
just did within a multi-step task.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

from loguru import logger


class WorkingMemory:
    """Process-wide live context (singleton)."""

    def __init__(self, max_observations: int = 10) -> None:
        self.active_app: str = "Desktop"
        self.last_screen_text: str = ""
        self.clipboard: str = ""
        self.current_task: str = ""
        self._observations: Deque[Dict[str, Any]] = deque(maxlen=max_observations)
        self._scratch: Dict[str, Any] = {}

    # ── Live context setters ──────────────────────────────────────────────────
    def set_active_app(self, app: str) -> None:
        if app and app.strip():
            self.active_app = app.strip()

    def set_screen_text(self, text: str) -> None:
        self.last_screen_text = (text or "")[:1500]

    def set_clipboard(self, text: str) -> None:
        self.clipboard = (text or "")[:1000]

    def start_task(self, task: str) -> None:
        self.current_task = (task or "").strip()
        self._observations.clear()

    def clear_task(self) -> None:
        self.current_task = ""
        self._observations.clear()

    def add_observation(self, tool: str, args: Dict[str, Any], result: str) -> None:
        self._observations.append({
            "tool": tool,
            "args": args or {},
            "result": (result or "")[:300],
            "ts": time.time(),
        })

    def recent_tools(self) -> List[str]:
        return [o["tool"] for o in self._observations]

    # ── Scratchpad (arbitrary short-lived key/values) ─────────────────────────
    def set(self, key: str, value: Any) -> None:
        self._scratch[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._scratch.get(key, default)

    # ── Prompt context ────────────────────────────────────────────────────────
    def context_snapshot(self) -> str:
        """Compact, LLM-friendly summary of the live situation (may be empty)."""
        lines: List[str] = []
        if self.active_app and self.active_app != "Desktop":
            lines.append(f"Active window: {self.active_app}")
        if self.current_task:
            lines.append(f"Current task: {self.current_task}")
        if self._observations:
            recent = "; ".join(f"{o['tool']}→{o['result'][:60]}" for o in list(self._observations)[-3:])
            lines.append(f"Recent actions: {recent}")
        return "\n".join(lines)


# Process-wide singleton
working_memory = WorkingMemory()
logger.debug("[Memory] Working memory (L2) ready.")
