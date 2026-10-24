"""
J.A.R.V.I.S. — Wake Word & Hotkey Trigger System
Supports:
  • "Hey Jarvis" wake word via Silero VAD + ONNX keyword model
  • Win+J keyboard hotkey
  • Runtime toggle between both / either
  • Win+Shift+J to toggle wake word on/off live
"""
from __future__ import annotations

import asyncio
import threading
import time
from enum import Enum, auto
from pathlib import Path
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
    Manages the two input trigger modes for Jarvis:
      1. Wake word ("Hey Jarvis")
      2. Keyboard hotkey (Win+J)

    Both can be active simultaneously. Each is independently toggleable
    at runtime — no restart required.
    """

    def __init__(self, on_trigger: Callable[[], None]):
        """
        Args:
            on_trigger: Async-compatible callback invoked when any trigger fires.
                        Called from a background thread — must be thread-safe.
        """
        cfg = load_config()
        self._on_trigger    = on_trigger
        self._lock          = threading.Lock()
        self._active        = False       # True while listening session is live

        # ── Config ───────────────────────────────────────────────────────
        self.wake_word_enabled: bool = cfg["wake_word"]["enabled"]
        self.hotkey_enabled:    bool = cfg["hotkey"]["enabled"]
        self._hotkey_combo:     str  = "+".join(cfg["hotkey"]["trigger_keys"])
        self._toggle_combo:     str  = "+".join(cfg["hotkey"]["toggle_wake_word"])

        # ── State ────────────────────────────────────────────────────────
        self._ww_thread:  Optional[threading.Thread] = None
        self._ww_running: bool = False

        logger.info(
            f"TriggerSystem init | wake_word={self.wake_word_enabled} "
            f"hotkey={self.hotkey_enabled} ({self._hotkey_combo})"
        )

    # ──────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────

    def start(self):
        """Start all enabled triggers."""
        self._register_hotkeys()
        if self.wake_word_enabled:
            self._start_wake_word_listener()
        logger.success("TriggerSystem started.")

    def stop(self):
        """Gracefully stop all triggers."""
        keyboard.unhook_all()
        self._stop_wake_word_listener()
        logger.info("TriggerSystem stopped.")

    def toggle_wake_word(self) -> bool:
        """
        Toggle the wake word listener on/off at runtime.
        Returns the new state (True = enabled).
        """
        if self.wake_word_enabled:
            self._stop_wake_word_listener()
            self.wake_word_enabled = False
            logger.info("Wake word DISABLED. Hotkey only.")
        else:
            self.wake_word_enabled = True
            self._start_wake_word_listener()
            logger.info("Wake word ENABLED.")
        return self.wake_word_enabled

    def toggle_hotkey(self) -> bool:
        """Toggle the keyboard hotkey on/off at runtime."""
        self.hotkey_enabled = not self.hotkey_enabled
        if self.hotkey_enabled:
            keyboard.add_hotkey(self._hotkey_combo, self._on_hotkey_fired)
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
    # Hotkey wiring
    # ──────────────────────────────────────────────────────────────────

    def _register_hotkeys(self):
        if self.hotkey_enabled:
            keyboard.add_hotkey(self._hotkey_combo, self._on_hotkey_fired)
            logger.debug(f"Hotkey registered: {self._hotkey_combo}")
        # The toggle hotkey is ALWAYS active regardless of mode
        keyboard.add_hotkey(self._toggle_combo, self._on_toggle_fired)
        logger.debug(f"Wake word toggle hotkey registered: {self._toggle_combo}")

    def _on_hotkey_fired(self):
        logger.debug("Hotkey triggered.")
        self._fire_trigger()

    def _on_toggle_fired(self):
        new_state = self.toggle_wake_word()
        # Notify the user via a brief spoken status (pipeline will handle this)
        state_str = "enabled" if new_state else "disabled"
        logger.info(f"[TOGGLE] Wake word is now {state_str}.")
        # The main pipeline listens on self.wake_word_enabled and will
        # speak confirmation if wired up.

    # ──────────────────────────────────────────────────────────────────
    # Wake word listener
    # ──────────────────────────────────────────────────────────────────

    def _start_wake_word_listener(self):
        if self._ww_running:
            return
        self._ww_running = True
        self._ww_thread  = threading.Thread(
            target=self._wake_word_loop,
            name="ww-listener",
            daemon=True,
        )
        self._ww_thread.start()
        logger.debug("Wake word listener thread started.")

    def _stop_wake_word_listener(self):
        self._ww_running = False
        if self._ww_thread and self._ww_thread.is_alive():
            self._ww_thread.join(timeout=2.0)
        self._ww_thread = None

    def _wake_word_loop(self):
        """
        Continuously listens for the "Hey Jarvis" wake phrase.
        Uses openWakeWord (ONNX) via Silero VAD pre-gating for efficiency.

        Note: openwakeword is installed in a Python 3.11 sidecar process
        and communicated with via a local pipe if needed. For now we use
        a direct ONNX inference approach.
        """
        try:
            import numpy as np
            import sounddevice as sd
            from jarvis.audio.wake_word_onnx import WakeWordDetector

            cfg = load_config()
            detector = WakeWordDetector(
                model_path=cfg["wake_word"]["model_path"],
                threshold=cfg["wake_word"]["sensitivity"],
            )

            sample_rate    = cfg["audio"]["sample_rate"]
            chunk_duration = 0.08   # 80ms chunks — low latency
            chunk_size     = int(sample_rate * chunk_duration)

            logger.info(f"Wake word loop running — listening for '{cfg['wake_word']['word']}'")

            with sd.InputStream(
                samplerate=sample_rate,
                channels=1,
                dtype="float32",
                blocksize=chunk_size,
                device=cfg["audio"]["input_device_index"],
            ) as stream:
                while self._ww_running:
                    audio_chunk, _ = stream.read(chunk_size)
                    audio_flat     = audio_chunk.flatten()
                    if detector.detect(audio_flat):
                        logger.success("🎙️  Wake word detected: 'Hey Jarvis'")
                        self._fire_trigger()
                        # Brief cooldown so a single utterance doesn't double-trigger
                        time.sleep(1.5)

        except Exception as e:
            logger.error(f"Wake word loop error: {e}")
            self._ww_running = False

    # ──────────────────────────────────────────────────────────────────
    # Common trigger dispatch
    # ──────────────────────────────────────────────────────────────────

    def _fire_trigger(self):
        """Thread-safe trigger dispatch — prevents overlapping sessions."""
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
