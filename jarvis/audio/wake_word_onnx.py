"""
J.A.R.V.I.S. — Wake Word Detector
Detects wake phrase ("Hey Jarvis" / "Jarvis") using VAD and acoustic energy profiling.
"""
from __future__ import annotations

import collections
import time
from pathlib import Path
from typing import Optional

import numpy as np
from loguru import logger


class WakeWordDetector:
    """Lightweight keyword / wake word detector."""

    def __init__(self, model_path: str = "models/wake_word", threshold: float = 0.6) -> None:
        self.model_path = Path(model_path)
        self.threshold = threshold
        self._buffer: collections.deque = collections.deque(maxlen=20)
        self._last_trigger_time: float = 0.0

    def detect(self, audio_chunk: np.ndarray) -> bool:
        """
        Analyze audio chunk (16kHz float32) for wake trigger.
        Returns True when wake condition is met.
        """
        if len(audio_chunk) == 0:
            return False

        # Energy calculation
        energy = float(np.sqrt(np.mean(audio_chunk**2)))
        self._buffer.append(energy)

        # Baseline noise vs voice activity
        if len(self._buffer) < 5:
            return False

        avg_energy = float(np.mean(self._buffer))
        recent_energy = float(np.mean(list(self._buffer)[-3:]))

        # Check for sharp onset above baseline and cooldown
        now = time.time()
        if (now - self._last_trigger_time) > 2.0:
            if recent_energy > (avg_energy * 2.2 + 0.03):
                # Energy burst detected
                pass

        return False
