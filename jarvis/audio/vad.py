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
    SPEECH_PAD_MS       = 250   # Pad before/after speech for natural capture
    MIN_SPEECH_MS       = 200   # Ignore very short bursts (<200ms) — noise
    MAX_SILENCE_MS      = 380   # Stop collecting after 380ms silence for snappy response
    PRE_SPEECH_BUFFER_MS= 200   # Rolling buffer before speech onset

    def __init__(
        self,
        on_speech_segment: Callable[[np.ndarray], None],
        is_speaking_fn: Optional[Callable[[], bool]] = None,
        speaker_verifier_fn: Optional[Callable[[np.ndarray], bool]] = None,
    ):
        """
        Args:
            on_speech_segment: Called with a float32 numpy array of 16kHz audio
                               when a complete speech segment is detected.
            is_speaking_fn: Optional callable returning True while Jarvis is speaking,
                            used to suppress acoustic echo from laptop speakers.
            speaker_verifier_fn: Optional callable to verify if audio matches enrolled user voiceprint.
        """
        self._callback            = on_speech_segment
        self._is_speaking_fn      = is_speaking_fn
        self._speaker_verifier_fn = speaker_verifier_fn
        self._cfg                 = load_config()
        self._threshold      = max(0.6, float(self._cfg["audio"]["vad_threshold"]))
        self._device_idx     = self._cfg["audio"]["input_device_index"]

        self._running        = False
        self._thread: Optional[threading.Thread] = None
        self._model          = None
        self._model_state    = None
        self._last_speaker_active_time = 0.0

        # ── Barge-in & Echo Suppression ──────────────────────────────────
        self._barge_in_enabled = False
        self._on_barge_in: Optional[Callable] = None
        self._speaker_started_time = 0.0
        self._last_barge_in_time = 0.0
        self._consecutive_barge_chunks = 0
        self._was_speaking = False

    # ──────────────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────────────

    def start(self):
        """Load Silero VAD and begin listening on the microphone."""
        logger.info("Loading Silero VAD v5...")
        torch.hub.set_dir("models/silero_vad")
        self._model, utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            trust_repo=True,
            verbose=False,
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

        target_device = self._device_idx if (self._device_idx is not None and self._device_idx >= 0) else None
        try:
            stream = sd.InputStream(
                samplerate=self.SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=self.CHUNK_SAMPLES,
                device=target_device,
            )
            logger.info(f"VAD listening on device {target_device} @ {self.SAMPLE_RATE}Hz")
        except Exception as e:
            logger.warning(f"Audio input device {target_device} failed ({e}), using system default microphone.")
            stream = sd.InputStream(
                samplerate=self.SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=self.CHUNK_SAMPLES,
                device=None,
            )
            logger.info(f"VAD listening on default input device @ {self.SAMPLE_RATE}Hz")

        with stream:
            while self._running:
                chunk, _ = stream.read(self.CHUNK_SAMPLES)
                audio    = chunk.flatten()

                # ── Echo Suppression & Voice Barge-in ──
                now = time.time()
                is_speaking = bool(self._is_speaking_fn and self._is_speaking_fn())
                if is_speaking:
                    if not self._was_speaking:
                        self._speaker_started_time = now
                        self._consecutive_barge_chunks = 0
                    self._was_speaking = True
                    self._last_speaker_active_time = now

                    # Grace period: do NOT trigger barge-in during the first 600ms of any utterance.
                    # Cooldown: enforce 1.5s between consecutive barge-in triggers to prevent self-interruption loops.
                    time_speaking = now - self._speaker_started_time
                    time_since_last_barge = now - self._last_barge_in_time

                    if self._barge_in_enabled and self._on_barge_in and time_speaking >= 0.6 and time_since_last_barge >= 1.5:
                        tensor = torch.from_numpy(audio)
                        prob = self._model(tensor, self.SAMPLE_RATE).item()
                        rms = float(np.sqrt(np.mean(audio ** 2)))

                        # Check speaker verification if voiceprints are enrolled
                        voice_verified = True
                        if self._speaker_verifier_fn:
                            try:
                                voice_verified = self._speaker_verifier_fn(audio)
                            except Exception:
                                voice_verified = True

                        # Genuine user voice interruption: verified voice + sustained loud speech (>= 0.14 RMS over speaker bleed)
                        # across at least 3 consecutive chunks (~100ms)
                        if voice_verified and prob >= 0.90 and rms >= 0.14:
                            self._consecutive_barge_chunks += 1
                            if self._consecutive_barge_chunks >= 3:
                                logger.info(f"🛑 Verified voice barge-in detected (prob={prob:.2f}, rms={rms:.3f})! Halting speech...")
                                self._last_barge_in_time = now
                                self._consecutive_barge_chunks = 0
                                self._on_barge_in()
                        else:
                            self._consecutive_barge_chunks = 0
                    else:
                        self._consecutive_barge_chunks = 0

                    in_speech = False
                    speech_chunks = []
                    silence_chunks = 0
                    pre_buf.clear()
                    continue

                self._was_speaking = False
                self._consecutive_barge_chunks = 0

                if (now - self._last_speaker_active_time) < 0.25:
                    # Dissipate room acoustic echo (250ms)
                    in_speech = False
                    speech_chunks = []
                    silence_chunks = 0
                    pre_buf.clear()
                    continue

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
