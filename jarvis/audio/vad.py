"""
J.A.R.V.I.S. — VAD (Voice Activity Detection)
Uses Silero VAD v5 (ONNX) to detect when the user starts and stops speaking.
Feeds clean speech segments to the STT engine.
"""
from __future__ import annotations

import collections
import io
import queue
import threading
import time
from typing import Callable, Optional

import numpy as np
import sounddevice as sd
import soundfile as sf
import torch
from loguru import logger

from jarvis.core.config import load_config


class VADListener:
    """
    Continuous voice activity detector.
    Uses Silero VAD v5 (runs on CPU, <2ms per 32ms chunk).

    Emits complete speech segments as raw PCM float32 arrays
    via the on_speech_segment callback.
    """

    # Silero VAD chunk sizes (fixed by the model)
    CHUNK_MS        = 32     # ms per inference
    SAMPLE_RATE     = 16000
    CHUNK_SAMPLES   = int(SAMPLE_RATE * CHUNK_MS / 1000)  # 512 samples

    # Timing parameters
    SPEECH_PAD_MS       = 300   # Pad before/after speech for natural capture
    MIN_SPEECH_MS       = 250   # Ignore very short bursts (<250ms) — noise
    MAX_SILENCE_MS      = 800   # Stop collecting after 800ms silence
    PRE_SPEECH_BUFFER_MS= 200   # Rolling buffer before speech onset

    def __init__(self, on_speech_segment: Callable[[np.ndarray], None]):
        """
        Args:
            on_speech_segment: Called with a float32 numpy array of 16kHz audio
                               when a complete speech segment is detected.
        """
        self._callback   = on_speech_segment
        self._cfg        = load_config()
        self._threshold  = self._cfg["audio"]["vad_threshold"]
        self._device_idx = self._cfg["audio"]["input_device_index"]

        self._running     = False
        self._thread: Optional[threading.Thread] = None
        self._model       = None
        self._model_state = None

        # ── Barge-in support ─────────────────────────────────────────────
        self._barge_in_enabled    = False
        self._on_barge_in: Optional[Callable] = None

    # ──────────────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────────────

    def start(self):
        """Load Silero VAD and begin listening on the microphone."""
        logger.info("Loading Silero VAD v5...")
        self._model, utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            trust_repo=True,
        )
        self._model.eval()
        logger.success("Silero VAD loaded.")

        self._running = True
        self._thread  = threading.Thread(
            target=self._listen_loop,
            name="vad-listener",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3.0)

    def enable_barge_in(self, callback: Callable):
        """
        Enable barge-in detection.
        When the user speaks while Jarvis is outputting audio,
        the callback is fired immediately so the pipeline can cancel TTS.
        """
        self._barge_in_enabled = True
        self._on_barge_in = callback

    def disable_barge_in(self):
        self._barge_in_enabled = False
        self._on_barge_in = None

    # ──────────────────────────────────────────────────────────────────
    # Core VAD loop
    # ──────────────────────────────────────────────────────────────────

    def _listen_loop(self):
        pre_speech_len = int(self.SAMPLE_RATE * self.PRE_SPEECH_BUFFER_MS / 1000 / self.CHUNK_SAMPLES)
        pre_buf        = collections.deque(maxlen=pre_speech_len)

        in_speech        = False
        speech_chunks    = []
        silence_chunks   = 0
        max_silence      = int(self.MAX_SILENCE_MS / self.CHUNK_MS)
        min_speech       = int(self.MIN_SPEECH_MS / self.CHUNK_MS)

        logger.info(f"VAD listening on device {self._device_idx} @ {self.SAMPLE_RATE}Hz")

        with sd.InputStream(
            samplerate=self.SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=self.CHUNK_SAMPLES,
            device=self._device_idx,
        ) as stream:
            while self._running:
                chunk, _ = stream.read(self.CHUNK_SAMPLES)
                audio    = chunk.flatten()

                # Silero VAD inference (in-process, ~1ms on CPU)
                tensor   = torch.from_numpy(audio)
                prob     = self._model(tensor, self.SAMPLE_RATE).item()
                is_voice = prob >= self._threshold

                if is_voice:
                    if not in_speech:
                        # Speech onset — prepend the rolling pre-buffer
                        logger.debug(f"🗣  Speech onset (VAD={prob:.2f})")
                        in_speech     = True
                        silence_chunks= 0
                        speech_chunks = list(pre_buf)  # capture leading audio

                        # Fire barge-in if Jarvis is currently speaking
                        if self._barge_in_enabled and self._on_barge_in:
                            self._on_barge_in()

                    speech_chunks.append(audio)
                    silence_chunks = 0

                elif in_speech:
                    speech_chunks.append(audio)
                    silence_chunks += 1

                    if silence_chunks >= max_silence:
                        # End of utterance
                        if len(speech_chunks) >= min_speech:
                            segment = np.concatenate(speech_chunks)
                            logger.debug(
                                f"📦 Speech segment ready: "
                                f"{len(segment)/self.SAMPLE_RATE:.2f}s"
                            )
                            self._callback(segment)
                        in_speech     = False
                        speech_chunks = []
                        silence_chunks= 0

                else:
                    # Not in speech — update rolling pre-buffer
                    pre_buf.append(audio)
