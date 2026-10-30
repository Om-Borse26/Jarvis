"""
J.A.R.V.I.S. — Voice Mood Engine
Analyzes acoustic features of the user's voice in real-time
to determine emotional state and adapt Jarvis's tone accordingly.

No camera required — purely audio-based analysis using librosa.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Deque

import numpy as np
from loguru import logger


@dataclass
class MoodState:
    mood:           str    = "neutral"
    confidence:     float  = 0.5
    tone_guidance:  str    = "Be crisp and direct."
    tts_speed:      float  = 1.0     # TTS speed multiplier
    response_length: str   = "normal" # "short" | "normal" | "detailed"
    temperature:    float  = 0.4     # LLM sampling temperature


# Tone guidance per mood — injected into LLM system prompt
MOOD_TONES = {
    "focused": (
        "The user is focused and working. Be crisp, technical, minimal filler. "
        "Skip pleasantries. Deliver results directly."
    ),
    "relaxed": (
        "The user is relaxed. You can be slightly more conversational and warm. "
        "Light wit is welcome."
    ),
    "stressed": (
        "The user sounds stressed. Be calm, reassuring, and concise. "
        "Offer to handle tasks proactively. Keep responses short."
    ),
    "tired": (
        "The user sounds tired. Be gentle, quieter, and brief. "
        "Offer to handle things silently in the background."
    ),
    "energized": (
        "The user is energized. Match the pace. Be dynamic and efficient."
    ),
    "neutral": (
        "Standard professional tone. Be direct and helpful."
    ),
}

MOOD_TTS_SPEED = {
    "focused":   1.05,
    "relaxed":   0.95,
    "stressed":  0.90,
    "tired":     0.85,
    "energized": 1.10,
    "neutral":   1.00,
}

MOOD_RESPONSE_LENGTH = {
    "focused":   "short",
    "relaxed":   "normal",
    "stressed":  "short",
    "tired":     "short",
    "energized": "normal",
    "neutral":   "normal",
}

# LLM sampling temperature per mood — crisp/low when focused or stressed,
# a touch warmer when relaxed. Keeps action selection deterministic.
MOOD_TEMPERATURE = {
    "focused":   0.25,
    "relaxed":   0.55,
    "stressed":  0.30,
    "tired":     0.35,
    "energized": 0.45,
    "neutral":   0.40,
}


class MoodEngine:
    """
    Extracts acoustic features from speech audio segments and
    classifies the user's emotional/cognitive state.

    Features analyzed:
      - Pitch (F0): mean, variance, range
      - Speech rate: syllable-level energy peaks per second
      - Energy (RMS): mean amplitude
      - Voice quality: zero-crossing rate (roughness proxy)
    """

    HISTORY_WINDOW = 5   # Number of recent speech segments to average over

    def __init__(self):
        self._history: Deque[dict] = deque(maxlen=self.HISTORY_WINDOW)
        self.current_mood = MoodState()
        self._last_update = 0.0

    def analyze(self, audio: np.ndarray, sample_rate: int = 16000) -> MoodState:
        """
        Analyze a speech segment and update mood state.

        Args:
            audio:       Float32 numpy array at sample_rate Hz.
            sample_rate: Audio sample rate.

        Returns:
            Updated MoodState.
        """
        try:
            import librosa

            # ── Feature extraction ────────────────────────────────────────
            # Pitch (F0) — via librosa pyin
            f0, voiced_flag, _ = librosa.pyin(
                audio,
                fmin=librosa.note_to_hz("C2"),
                fmax=librosa.note_to_hz("C7"),
                sr=sample_rate,
            )
            f0_valid = f0[voiced_flag] if voiced_flag is not None else np.array([])

            pitch_mean = float(np.nanmean(f0_valid)) if len(f0_valid) > 0 else 150.0
            pitch_var  = float(np.nanstd(f0_valid))  if len(f0_valid) > 0 else 20.0

            # Energy (RMS)
            rms       = librosa.feature.rms(y=audio)[0]
            energy    = float(np.mean(rms))

            # Speech rate proxy — peaks in onset strength envelope
            onset_env  = librosa.onset.onset_strength(y=audio, sr=sample_rate)
            onset_mean = float(np.mean(onset_env))
            duration   = len(audio) / sample_rate
            rate       = float(np.sum(onset_env > onset_mean * 1.5)) / max(duration, 0.1)

            # Zero-crossing rate — roughness/tension in voice
            zcr        = float(np.mean(librosa.feature.zero_crossing_rate(audio)))

            features = {
                "pitch_mean": pitch_mean,
                "pitch_var":  pitch_var,
                "energy":     energy,
                "rate":       rate,
                "zcr":        zcr,
            }
            self._history.append(features)

            # Average over recent history for stability
            avg = {k: np.mean([h[k] for h in self._history]) for k in features}

            mood = self._classify(avg)
            self.current_mood = MoodState(
                mood           = mood,
                confidence     = 0.75,
                tone_guidance  = MOOD_TONES[mood],
                tts_speed      = MOOD_TTS_SPEED[mood],
                response_length= MOOD_RESPONSE_LENGTH[mood],
                temperature    = MOOD_TEMPERATURE[mood],
            )
            logger.debug(
                f"Mood: {mood} | pitch={avg['pitch_mean']:.0f}Hz "
                f"var={avg['pitch_var']:.0f} energy={avg['energy']:.4f} "
                f"rate={avg['rate']:.1f} zcr={avg['zcr']:.4f}"
            )

        except Exception as e:
            logger.warning(f"Mood analysis error: {e}")

        return self.current_mood

    def _classify(self, f: dict) -> str:
        """Rule-based mood classifier from acoustic features."""
        pitch  = f["pitch_mean"]
        p_var  = f["pitch_var"]
        energy = f["energy"]
        rate   = f["rate"]
        zcr    = f["zcr"]

        # Tired: low energy, low pitch, slow rate
        if energy < 0.01 and rate < 3.0 and pitch < 160:
            return "tired"

        # Stressed: high ZCR, high rate, elevated pitch variance
        if zcr > 0.15 and rate > 8.0 and p_var > 60:
            return "stressed"

        # Energized: high energy, high rate, high pitch
        if energy > 0.04 and rate > 7.0 and pitch > 200:
            return "energized"

        # Focused: moderate energy, moderate rate, low variance (flat speech)
        if 0.015 < energy < 0.04 and p_var < 40 and 4.0 < rate < 8.0:
            return "focused"

        # Relaxed: low-moderate energy, slow pace
        if energy < 0.025 and rate < 5.0:
            return "relaxed"

        return "neutral"
