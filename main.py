"""
J.A.R.V.I.S. — Entry Point
Run this to start Jarvis.

Usage:
    python main.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from loguru import logger

# ── Logging setup ──────────────────────────────────────────────────────
LOG_DIR = Path("data") / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logger.remove()  # Remove default stderr logger
logger.add(
    sys.stderr,
    format=(
        "<green>{time:HH:mm:ss}</green> | "
        "<level>{level:<8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{line}</cyan> — <level>{message}</level>"
    ),
    level="INFO",
    colorize=True,
)
logger.add(
    LOG_DIR / "jarvis_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="30 days",
    compression="zip",
    level="DEBUG",
    encoding="utf-8",
)


async def main():
    from jarvis.core.pipeline import JarvisPipeline

    pipeline = JarvisPipeline()
    try:
        await pipeline.start()
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user.")
    except RuntimeError as e:
        logger.error(str(e))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
