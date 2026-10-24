"""
J.A.R.V.I.S. — Wake Word & Hotkey Trigger System
Supports:
  • "Hey Jarvis" / "Jarvis" wake phrase recognition
  • Win+J keyboard hotkey
  • Runtime toggle between wake word and hotkey modes
  • Win+Shift+J to toggle wake word on/off live
"""
from __future__ import annotations

import threading
from enum import Enum, auto
from typing import Callable, Optional

import keyboard
from loguru import logger

from jarvis.core.config import load_config


class TriggerMode(Enum):
    WAKE_WORD_ONLY = auto()
    HOTKEY_ONLY    = auto()
    BOTH           = auto()


class TriggerSystem:
    """
    Manages input trigger modes for Jarvis:
      1. Wake word ("Hey Jarvis" / "Jarvis")
      2. Keyboard hotkey (Win+J)
      3. Live mode toggle (Win+Shift+J)
    """

    def __init__(self, on_trigger: Callable[[], None], on_mode_change: Optional[Callable[[bool], None]] = None):
        """
        Args:
            on_trigger: Callback invoked when any trigger fires.
            on_mode_change: Callback invoked when wake word is toggled on/off.
        """
        cfg = load_config()
        self._on_trigger = on_trigger
        self._on_mode_change = on_mode_change
        self._lock = threading.Lock()
        self._active = False

        # Config
        self.wake_word_enabled: bool = cfg.get("wake_word", {}).get("enabled", True)
        self.hotkey_enabled: bool = cfg.get("hotkey", {}).get("enabled", True)
        self._hotkey_combo: str = "+".join(cfg.get("hotkey", {}).get("trigger_keys", ["win", "j"]))
        self._toggle_combo: str = "+".join(cfg.get("hotkey", {}).get("toggle_wake_word", ["win", "shift", "j"]))

        logger.info(
            f"TriggerSystem init | wake_word={self.wake_word_enabled} "
            f"hotkey={self.hotkey_enabled} ({self._hotkey_combo})"
        )

    def start(self):
        """Register hotkeys and arm trigger system."""
        self._register_hotkeys()
        logger.success("TriggerSystem started.")

    def stop(self):
        """Gracefully release all hotkeys."""
        try:
            keyboard.unhook_all()
        except Exception as e:
            logger.debug(f"Hotkey unhook notice: {e}")
        logger.info("TriggerSystem stopped.")

    def is_wake_word(self, text: str) -> bool:
        """Check if transcribed speech contains the wake phrase."""
        clean = text.lower().strip()
        wake_patterns = ["hey jarvis", "hi jarvis", "ok jarvis", "okay jarvis", "jarvis"]
        return any(clean.startswith(p) or f" {p}" in clean for p in wake_patterns)

    def strip_wake_word(self, text: str) -> str:
        """Remove wake phrase prefix from user input."""
        clean = text.strip()
        lower = clean.lower()
        for p in ["hey jarvis", "hi jarvis", "ok jarvis", "okay jarvis", "jarvis"]:
            if lower.startswith(p):
                clean = clean[len(p):].lstrip(",.?! ")
                break
        return clean

    def toggle_wake_word(self) -> bool:
        """Toggle the wake word listener on/off at runtime."""
        self.wake_word_enabled = not self.wake_word_enabled
        state_str = "ENABLED" if self.wake_word_enabled else "DISABLED (Hotkey only)"
        logger.info(f"[TOGGLE] Wake word is now {state_str}.")
        if self._on_mode_change:
            self._on_mode_change(self.wake_word_enabled)
        return self.wake_word_enabled

    def toggle_hotkey(self) -> bool:
        """Toggle the keyboard hotkey on/off at runtime."""
        self.hotkey_enabled = not self.hotkey_enabled
        if self.hotkey_enabled:
            self._register_hotkeys()
            logger.info(f"Hotkey ENABLED ({self._hotkey_combo}).")
        else:
            try:
                keyboard.remove_hotkey(self._hotkey_combo)
            except Exception:
                pass
            logger.info("Hotkey DISABLED.")
        return self.hotkey_enabled

    @property
    def mode(self) -> TriggerMode:
        if self.wake_word_enabled and self.hotkey_enabled:
            return TriggerMode.BOTH
        elif self.wake_word_enabled:
            return TriggerMode.WAKE_WORD_ONLY
        return TriggerMode.HOTKEY_ONLY

    # ──────────────────────────────────────────────────────────────────
    # Internal Hotkey Handlers
    # ──────────────────────────────────────────────────────────────────

    def _register_hotkeys(self):
        try:
            if self.hotkey_enabled:
                keyboard.add_hotkey(self._hotkey_combo, self._on_hotkey_fired)
                logger.debug(f"Hotkey registered: {self._hotkey_combo}")
            keyboard.add_hotkey(self._toggle_combo, self._on_toggle_fired)
            logger.debug(f"Wake word toggle hotkey registered: {self._toggle_combo}")
        except Exception as e:
            logger.warning(f"Could not register system hotkey ({e}). Running in voice/VAD mode.")

    def _on_hotkey_fired(self):
        logger.info("⌨️  Hotkey triggered (Win+J).")
        self._fire_trigger()

    def _on_toggle_fired(self):
        self.toggle_wake_word()

    def _fire_trigger(self):
        with self._lock:
            if self._active:
                logger.debug("Trigger ignored — session already active.")
                return
            self._active = True
        try:
            self._on_trigger()
        finally:
            with self._lock:
                self._active = False
