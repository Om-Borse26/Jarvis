"""
J.A.R.V.I.S. — Speech-to-Text Engine
Powered by Faster-Whisper (distil-medium.en) on CUDA.
Target: < 220ms for a 5-second utterance.
"""
from __future__ import annotations

import io
import time
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf
from loguru import logger

from jarvis.core.config import load_config


class STTEngine:
    """
    Transcribes speech segments to text using Faster-Whisper.
    Model is loaded once and kept resident in VRAM for low latency.
    """

    def __init__(self):
        self._cfg         = load_config()["stt"]
        self._model       = None
        self._model_name  = self._cfg["model"]
        self._model_path  = self._cfg["model_path"]
        self._device      = self._cfg["device"]       # "cuda" or "cpu"
        self._compute     = self._cfg["compute_type"] # "float16" on CUDA
        self._beam_size   = self._cfg["beam_size"]
        self._language    = self._cfg["language"]

    def load(self):
        """Load the Whisper model. Call once at startup."""
        import os
        torch_lib = Path(__file__).resolve().parent.parent.parent / ".venv" / "Lib" / "site-packages" / "torch" / "lib"
        if torch_lib.exists():
            try:
                os.add_dll_directory(str(torch_lib))
            except Exception:
                pass
            os.environ["PATH"] = str(torch_lib) + os.pathsep + os.environ.get("PATH", "")

        from faster_whisper import WhisperModel

        logger.info(f"Loading Faster-Whisper: {self._model_name} on {self._device}...")
        t0 = time.perf_counter()

        self._model = WhisperModel(
            model_size_or_path=self._model_name,
            device=self._device,
            compute_type=self._compute,
            download_root=self._model_path,
        )

        elapsed = (time.perf_counter() - t0) * 1000
        logger.success(f"Faster-Whisper loaded in {elapsed:.0f}ms.")

    def transcribe(self, audio: np.ndarray) -> str:
        """
        Transcribe a float32, 16kHz mono audio array to text.

        Args:
            audio: numpy float32 array at 16000 Hz sample rate

        Returns:
            Transcribed text string.
        """
        if self._model is None:
            raise RuntimeError("STTEngine not loaded. Call .load() first.")

        if len(audio) < 16000 * 0.35:  # Under 350ms is too short for real speech
            return ""

        # Reject low-energy background silence / fan noise
        rms = float(np.sqrt(np.mean(audio**2)))
        if rms < 0.006:
            return ""

        t0 = time.perf_counter()

        segments, info = self._model.transcribe(
            audio,
            beam_size=self._beam_size,
            language=self._language,
            vad_filter=False,
            word_timestamps=False,
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
        )

        valid_texts = []
        ghost_phrases = {"thank you.", "thanks for watching.", "you", "bye.", "goodbye."}
        for seg in segments:
            no_speech = getattr(seg, "no_speech_prob", 0.0)
            if no_speech < 0.65:
                clean_seg = seg.text.strip()
                if clean_seg and clean_seg.lower() not in ghost_phrases:
                    valid_texts.append(clean_seg)

        text = " ".join(valid_texts).strip()

        elapsed = (time.perf_counter() - t0) * 1000
        logger.debug(
            f"STT: '{text[:80]}{'...' if len(text)>80 else ''}' "
            f"[{elapsed:.0f}ms, lang={info.language}]"
        )

        return text

    def transcribe_file(self, path: str | Path) -> str:
        """Transcribe an audio file (any format soundfile supports)."""
        audio, sr = sf.read(str(path), dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)   # Downmix to mono
        return self.transcribe(audio)
