"""
J.A.R.V.I.S. — Speaker Identification & Voiceprint Biometrics
Ensures Jarvis only responds to and is interrupted by the authorized user(s).
Blocks unauthorized voices (parents, friends, TV, background noise) and
prevents Jarvis from ever being interrupted by his own speaker playback.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple
import numpy as np
import librosa
from loguru import logger

VOICEPRINT_DIR = Path("data/voiceprints")


class SpeakerIdentifier:
    """Manages voiceprint enrollment, storage, and real-time verification."""

    def __init__(self, voiceprint_dir: Path | str = VOICEPRINT_DIR) -> None:
        self.voiceprint_dir = Path(voiceprint_dir)
        self.voiceprint_dir.mkdir(parents=True, exist_ok=True)
        self._enrolled_speakers: dict[str, np.ndarray] = {}
        self.load_enrolled_speakers()

    def extract_voiceprint(self, audio: np.ndarray, sr: int = 16000) -> Optional[np.ndarray]:
        """
        Extract a normalized 44-dimensional acoustic voiceprint embedding from speech.
        Uses MFCCs, spectral shape, and temporal energy distribution.
        """
        if len(audio) < int(sr * 0.25):  # Require at least 250ms of audio
            return None

        try:
            # 1. Mel-Frequency Cepstral Coefficients (Vocal tract characteristics)
            mfcc = librosa.feature.mfcc(y=audio, sr=sr, n_mfcc=20)
            mfcc_mean = np.mean(mfcc, axis=1)
            mfcc_std = np.std(mfcc, axis=1)

            # 2. Spectral Dynamics (Brightness, formant bandwidth)
            sc = np.mean(librosa.feature.spectral_centroid(y=audio, sr=sr))
            sb = np.mean(librosa.feature.spectral_bandwidth(y=audio, sr=sr))
            sr_feat = np.mean(librosa.feature.spectral_rolloff(y=audio, sr=sr))
            zcr = np.mean(librosa.feature.zero_crossing_rate(audio))

            # Combine into normalized embedding
            features = np.concatenate([
                mfcc_mean,
                mfcc_std,
                [sc / 1000.0, sb / 1000.0, sr_feat / 1000.0, zcr * 10.0]
            ])
            norm = np.linalg.norm(features)
            if norm == 0:
                return None
            return features / norm
        except Exception as e:
            logger.debug(f"Voiceprint extraction notice: {e}")
            return None

    def enroll(self, name: str, audio: np.ndarray, sr: int = 16000) -> bool:
        """Enroll a speaker from an audio sample and persist to disk."""
        embedding = self.extract_voiceprint(audio, sr=sr)
        if embedding is None:
            logger.warning(f"Audio sample too short or invalid to enroll {name}.")
            return False

        clean_name = name.lower().strip().replace(" ", "_")
        file_path = self.voiceprint_dir / f"{clean_name}.npy"
        np.save(str(file_path), embedding)
        self._enrolled_speakers[clean_name] = embedding
        logger.success(f"Voiceprint enrolled successfully for '{name}' -> {file_path}")
        return True

    def load_enrolled_speakers(self) -> int:
        """Load all saved voiceprints from disk."""
        count = 0
        for npy_file in self.voiceprint_dir.glob("*.npy"):
            try:
                name = npy_file.stem
                emb = np.load(str(npy_file))
                self._enrolled_speakers[name] = emb
                count += 1
            except Exception as e:
                logger.error(f"Failed to load voiceprint {npy_file}: {e}")
        if count > 0:
            logger.info(f"Loaded {count} enrolled voiceprint(s): {list(self._enrolled_speakers.keys())}")
        return count

    def verify(self, audio: np.ndarray, sr: int = 16000, threshold: float = 0.70) -> Tuple[bool, float, Optional[str]]:
        """
        Verify if the audio sample matches any enrolled authorized speaker.

        Returns:
            (is_authorized, best_similarity, speaker_name)
        """
        if not self._enrolled_speakers:
            # No speakers enrolled yet; default to allowing all
            return True, 1.0, "default_user"

        embedding = self.extract_voiceprint(audio, sr=sr)
        if embedding is None:
            return False, 0.0, None

        best_sim = -1.0
        best_name = None

        for name, enrolled_emb in self._enrolled_speakers.items():
            sim = float(np.dot(embedding, enrolled_emb))
            if sim > best_sim:
                best_sim = sim
                best_name = name

        is_authorized = best_sim >= threshold
        return is_authorized, best_sim, best_name if is_authorized else None


# Global singleton instance
speaker_id = SpeakerIdentifier()
