"""
J.A.R.V.I.S. — Text-to-Speech Engine
Powered by Kokoro-82M (ONNX) — natural, low-latency Jarvis voice.
Target: < 80ms to first audio byte.
"""
from __future__ import annotations

import asyncio
import queue
import threading
import time
from pathlib import Path
from typing import Optional, Callable

import numpy as np
import sounddevice as sd
from loguru import logger

from jarvis.core.config import load_config


class TTSEngine:
    """
    Streams Kokoro-82M synthesis directly to the speaker.

    Supports:
      - Sentence-chunked streaming (speak as text arrives)
      - Immediate interruption / mute for barge-in
      - Tracking of spoken vs. interrupted text for Steer Arbiter
    """

    def __init__(self):
        self._cfg         = load_config()["tts"]
        self._tts         = None
        self._voice       = self._cfg["voice"]
        self._speed       = self._cfg["speed"]
        self._model_path  = self._cfg["model_path"]

        cfg_audio         = load_config()["audio"]
        self._sample_rate = 24000    # Kokoro native output rate
        self._out_device  = cfg_audio["output_device_index"]

        # Playback state
        self._stream: Optional[sd.OutputStream] = None
        self._speaking        = False
        self._cancel_event    = threading.Event()

        # For Steer Arbiter tracking
        self.spoken_text      = ""
        self.interrupted_text = ""

        # Callback fired on start/stop of speech (for HUD animation sync)
        self.on_speaking_start: Optional[Callable] = None
        self.on_speaking_stop:  Optional[Callable] = None

    def load(self):
        """Load Kokoro model. Call once at startup."""
        from kokoro_onnx import Kokoro

        logger.info("Loading Kokoro-82M TTS...")
        t0  = time.perf_counter()
        self._tts = Kokoro(
            model_path=str(Path(self._model_path) / "kokoro-v1.0.onnx"),
            voices_path=str(Path(self._model_path) / "voices-v1.0.bin"),
        )
        elapsed = (time.perf_counter() - t0) * 1000
        logger.success(f"Kokoro TTS loaded in {elapsed:.0f}ms.")

    def speak(self, text: str, sentence_chunks: bool = True):
        """
        Synthesize and play text. Blocks until playback completes or is cancelled.

        Args:
            text:             The full text to speak.
            sentence_chunks:  If True, synthesizes sentence-by-sentence for
                              lower latency to first audio byte.
        """
        if not text.strip():
            return

        self._cancel_event.clear()
        self._speaking        = True
        self.spoken_text      = ""
        self.interrupted_text = text

        if self.on_speaking_start:
            self.on_speaking_start()

        try:
            if sentence_chunks:
                self._speak_chunked(text)
            else:
                self._speak_full(text)
        finally:
            self._speaking = False
            if self.on_speaking_stop:
                self.on_speaking_stop()

    def interrupt(self):
        """
        Immediately stop playback (barge-in / cancellation).
        Updates spoken_text and interrupted_text for Steer Arbiter.
        """
        if self._speaking:
            logger.debug("TTS interrupted.")
            self._cancel_event.set()

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    # ──────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────

    def _speak_chunked(self, text: str):
        """Split text at sentence boundaries and stream each chunk."""
        import re
        # Split on sentence endings but keep delimiter
        sentences = re.split(r'(?<=[.!?])\s+', text)
        sentences = [s.strip() for s in sentences if s.strip()]

        remaining = list(sentences)
        for sentence in sentences:
            if self._cancel_event.is_set():
                # Update interrupted_text = everything NOT yet spoken
                self.interrupted_text = " ".join(remaining)
                break
            self._synthesize_and_play(sentence)
            self.spoken_text += (" " if self.spoken_text else "") + sentence
            remaining.pop(0)

        if not self._cancel_event.is_set():
            self.interrupted_text = ""

    def _speak_full(self, text: str):
        self._synthesize_and_play(text)
        if not self._cancel_event.is_set():
            self.spoken_text      = text
            self.interrupted_text = ""

    def _synthesize_and_play(self, text: str):
        """Synthesize one chunk and play it to the speaker."""
        t0 = time.perf_counter()
        samples, sample_rate = self._tts.create(
            text,
            voice=self._voice,
            speed=self._speed,
            lang="en-us",
        )
        t_synth = (time.perf_counter() - t0) * 1000
        logger.debug(f"TTS synth: '{text[:50]}' → {t_synth:.0f}ms")

        audio = np.array(samples, dtype=np.float32)

        # Stream to speaker with cancellation support
        chunk_size = 2048
        with sd.OutputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            device=self._out_device,
        ) as stream:
            for i in range(0, len(audio), chunk_size):
                if self._cancel_event.is_set():
                    stream.abort()
                    break
                chunk = audio[i : i + chunk_size]
                stream.write(chunk)
