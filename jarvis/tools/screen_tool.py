"""
J.A.R.V.I.S. — Screen & Vision Tool
Captures desktop screens and provides OCR and multimodal analysis.
Enables Jarvis to 'see' what is currently on the user's screen.
"""
from __future__ import annotations

import io
import time
from pathlib import Path
from typing import Any

from loguru import logger
from PIL import ImageGrab


class ScreenTool:
    """Tool for screen capture, OCR, and visual context."""

    def __init__(self, output_dir: Path | str = "data/screenshots") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._ocr_reader = None

    def capture_screen(self) -> Path:
        """Capture the full primary display and save to disk."""
        screenshot = ImageGrab.grab()
        timestamp = int(time.time() * 1000)
        file_path = self.output_dir / f"screen_{timestamp}.png"
        screenshot.save(file_path, "PNG")
        logger.info(f"Captured screen to {file_path}")
        return file_path

    async def get_screen_text(self) -> dict[str, Any]:
        """Extract visible text from current screen using EasyOCR."""
        try:
            import easyocr

            if self._ocr_reader is None:
                self._ocr_reader = easyocr.Reader(["en"], gpu=True)

            img_path = self.capture_screen()
            results = self._ocr_reader.readtext(str(img_path), detail=0)
            extracted_text = " ".join(results)

            return {
                "status": "success",
                "image_path": str(img_path),
                "text_snippet": extracted_text[:1000],
                "all_text": extracted_text,
            }
        except Exception as e:
            logger.error(f"OCR extraction failed: {e}")
            return {"status": "error", "message": str(e)}
