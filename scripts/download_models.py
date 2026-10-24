"""
J.A.R.V.I.S. — Model Download Script
Downloads all required HuggingFace models to local directories.
Run once during setup: python scripts/download_models.py

Models downloaded:
  1. Faster-Whisper distil-medium.en  → models/whisper/
  2. Kokoro-82M (voice + weights)     → models/kokoro/
  3. all-MiniLM-L6-v2 (embeddings)   → models/minilm/
  4. Silero VAD v5                    → models/silero_vad/  (via torch.hub)
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

ROOT = Path(__file__).parent.parent
MODELS = ROOT / "models"


def download_whisper():
    logger.info("📥 Downloading Faster-Whisper distil-medium.en...")
    from faster_whisper import WhisperModel
    model = WhisperModel(
        "Systran/faster-distil-whisper-medium.en",
        device="cpu",          # Download only — will use CUDA at runtime
        compute_type="int8",
        download_root=str(MODELS / "whisper"),
    )
    logger.success("✅ Faster-Whisper downloaded.")
    del model


def download_kokoro():
    logger.info("📥 Downloading Kokoro-82M TTS model...")
    import urllib.request
    import shutil

    kokoro_dir = MODELS / "kokoro"
    kokoro_dir.mkdir(parents=True, exist_ok=True)

    base_url = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
    files = ["kokoro-v1.0.onnx", "voices-v1.0.bin"]

    for fname in files:
        path = kokoro_dir / fname
        if path.exists() and path.stat().st_size > 1000:
            logger.info(f"  ↳ {fname} already exists, skipping.")
            continue
        logger.info(f"  ↳ Downloading {fname}...")
        url = f"{base_url}/{fname}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as resp, open(path, "wb") as out_file:
            shutil.copyfileobj(resp, out_file)
        logger.success(f"  ✅ {fname} downloaded ({path.stat().st_size // (1024*1024)} MB).")
    logger.success("✅ Kokoro-82M downloaded.")


def download_minilm():
    logger.info("📥 Downloading all-MiniLM-L6-v2 embeddings model...")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(
        "sentence-transformers/all-MiniLM-L6-v2",
        cache_folder=str(MODELS / "minilm"),
    )
    logger.success("✅ all-MiniLM-L6-v2 downloaded.")
    del model


def download_silero_vad():
    logger.info("📥 Downloading Silero VAD v5...")
    import torch
    torch.hub.set_dir(str(MODELS / "silero_vad"))
    model, _ = torch.hub.load(
        repo_or_dir="snakers4/silero-vad",
        model="silero_vad",
        trust_repo=True,
        verbose=False,
    )
    logger.success("✅ Silero VAD downloaded.")
    del model


def verify_ollama_models():
    logger.info("🔍 Checking Ollama models...")
    import subprocess
    result = subprocess.run(
        ["ollama", "list"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        logger.info(f"Ollama models:\n{result.stdout}")
        required = ["qwen3.5:4b"]
        missing  = [m for m in required if m not in result.stdout]
        if missing:
            logger.warning(f"Missing models: {missing}")
            for m in missing:
                logger.info(f"Pulling {m}...")
                subprocess.run(["ollama", "pull", m])
        else:
            logger.success("✅ All required Ollama models present.")
    else:
        logger.error("Ollama not running. Start Ollama from the system tray and re-run.")


if __name__ == "__main__":
    logger.info("=" * 55)
    logger.info("  J.A.R.V.I.S. — Model Download Setup")
    logger.info("=" * 55)

    steps = [
        ("Silero VAD",     download_silero_vad),
        ("Faster-Whisper", download_whisper),
        ("Kokoro-82M TTS", download_kokoro),
        ("MiniLM Embeds",  download_minilm),
        ("Ollama Models",  verify_ollama_models),
    ]

    for name, fn in steps:
        try:
            fn()
        except Exception as e:
            logger.error(f"Failed to download {name}: {e}")
            logger.info("Continuing with remaining downloads...")

    logger.success("\n🎉 All models downloaded. You can now run: python main.py")
