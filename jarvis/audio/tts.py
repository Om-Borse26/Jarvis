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

import re
import numpy as np
import sounddevice as sd
from loguru import logger

from jarvis.core.config import load_config


def clean_text_for_speech(text: str) -> str:
    """
    Sanitize text before TTS synthesis so symbols, markdown, and acronyms
    are never vocalized awkwardly.

    Guarantees:
      - 'J.A.R.V.I.S.' / 'JARVIS' -> 'Jarvis' (single natural word)
      - Strips all asterisks (*, **), hashes (#), bullet points (-, •)
      - Strips code blocks, backticks, emojis, and HTML/XML tags
      - Expands '&' to 'and', '%' to 'percent', '+' to 'plus'
      - Preserves natural sentence punctuation (., !, ?) for human-like cadence
    """
    if not text:
        return ""

    # Strip XML / HTML tags (e.g. <think>...</think>)
    text = re.sub(r"<[^>]+>", " ", text)

    # Convert J.A.R.V.I.S. variants to single natural word Jarvis
    text = re.sub(r"\bJ\.?A\.?R\.?V\.?I\.?S\.?", "Jarvis", text, flags=re.IGNORECASE)

    # Remove markdown link syntax [title](url) -> title
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)

    # Remove code fences and backticks
    text = re.sub(r"```[a-zA-Z]*\n?", " ", text)
    text = text.replace("```", " ").replace("`", " ")

    # Remove markdown headers (#, ##, etc.)
    text = re.sub(r"(?m)^\s*#{1,6}\s*", "", text)
    text = re.sub(r"#{1,6}\s*", "", text)

    # Remove bullet markers at the start of a line (*, -, +, •)
    text = re.sub(r"(?m)^\s*[\*\-\+\•]\s*", "", text)
    # Bullet points inside text -> replace with comma pause
    text = re.sub(r"\s+[\*\-\+\•]\s+", ", ", text)

    # Strip all remaining asterisks, underscores, and tildes
    text = text.replace("*", "").replace("_", " ").replace("~", " ")

    # Expand spoken symbols
    text = text.replace("&", " and ")
    text = text.replace("%", " percent ")
    text = text.replace("@", " at ")
    text = text.replace("=", " equals ")
    text = text.replace("+", " plus ")

    # Strip other raw symbols that TTS engines vocalize awkwardly
    text = re.sub(r"[\/\\\|\<\>\{\}\[\]\^\~]", " ", text)

    # Strip emojis
    text = re.sub(r"[\U00010000-\U0010ffff]", "", text)

    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()

    # Clean up awkward punctuation spacing
    text = re.sub(r"\s+([,\.!\?:])", r"\1", text)
    text = text.replace(":,", ": ").replace(",,", ",")
    text = re.sub(r"([,\.!\?]){2,}", r"\1", text)

    return text.strip()


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
        self._voice       = self._cfg.get("voice", "bm_george")
        self._speed       = float(self._cfg.get("speed", 1.15))
        self.speed_mult   = 1.0   # Runtime multiplier (mood-driven; 1.0 = config speed)
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
        text = clean_text_for_speech(text)
        if not text:
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
        # Split on sentence endings but keep delimiter
        sentences = re.split(r'(?<=[.!?])\s+', text)
        sentences = [clean_text_for_speech(s) for s in sentences]
        sentences = [s for s in sentences if s]

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
        clean = clean_text_for_speech(text)
        if not clean or self._tts is None:
            return

        t0 = time.perf_counter()
        samples, sample_rate = self._tts.create(
            clean,
            voice=self._voice,
            speed=self._speed * max(0.5, min(1.5, self.speed_mult)),
            lang="en-us",
        )
        t_synth = (time.perf_counter() - t0) * 1000
        logger.debug(f"TTS synth: '{text[:50]}' → {t_synth:.0f}ms")

        audio = np.array(samples, dtype=np.float32)

        # Stream to speaker with cancellation support
        chunk_size = 2048
        target_device = self._out_device if (self._out_device is not None and self._out_device >= 0) else None
        try:
            stream = sd.OutputStream(
                samplerate=sample_rate,
                channels=1,
                dtype="float32",
                device=target_device,
            )
        except Exception as e:
            logger.warning(f"Audio output device {target_device} failed ({e}), using system default speaker.")
            stream = sd.OutputStream(
                samplerate=sample_rate,
                channels=1,
                dtype="float32",
                device=None,
            )

        with stream:
            for i in range(0, len(audio), chunk_size):
                if self._cancel_event.is_set():
                    stream.abort()
                    break
                chunk = audio[i : i + chunk_size]
                stream.write(chunk)
