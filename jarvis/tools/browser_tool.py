"""
J.A.R.V.I.S. — Browser Tool
Controls web interactions, searches, and automations.
Defaults to Brave Browser (ad-free) as specified by the user.
Falls back to system default or Chrome only on explicit instruction.
"""
from __future__ import annotations

import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any

from loguru import logger

BRAVE_PATHS = [
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
]


class BrowserTool:
    """Tool for controlling browser and web searches."""

    def __init__(self, default_browser: str = "brave") -> None:
        self.default_browser = default_browser
        self._brave_path = self._find_brave()

    def _find_brave(self) -> str | None:
        for p in BRAVE_PATHS:
            if Path(p).exists():
                return p
        return None

    async def open_url(self, url: str, browser: str | None = None) -> dict[str, Any]:
        """Open a URL in the designated browser (defaults to Brave)."""
        target_browser = (browser or self.default_browser).lower()

        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        try:
            if target_browser == "brave" and self._brave_path:
                import subprocess

                subprocess.Popen([self._brave_path, url])
                return {"status": "success", "message": f"Opened {url} in Brave Browser."}
            else:
                # System browser fallback
                webbrowser.open(url)
                return {"status": "success", "message": f"Opened {url}."}
        except Exception as e:
            logger.error(f"Error opening browser URL {url}: {e}")
            return {"status": "error", "message": str(e)}

    async def search(self, query: str, engine: str = "google", browser: str | None = None) -> dict[str, Any]:
        """Perform a web search using specified engine."""
        encoded = urllib.parse.quote_plus(query)
        if engine == "youtube":
            url = f"https://www.youtube.com/results?search_query={encoded}"
        elif engine == "brave":
            url = f"https://search.brave.com/search?q={encoded}"
        else:
            url = f"https://www.google.com/search?q={encoded}"

        return await self.open_url(url, browser=browser)
