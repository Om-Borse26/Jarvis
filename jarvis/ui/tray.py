"""
J.A.R.V.I.S. — System Tray
A background tray icon so Jarvis is reachable while it runs silently:
  - Open Dashboard
  - Stop Jarvis (clean shutdown)

Runs in a daemon thread; degrades gracefully if pystray isn't installed.
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

from loguru import logger


def _make_icon_image():
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((8, 8, 56, 56), fill=(30, 144, 255, 255))      # outer glow
    d.ellipse((20, 20, 44, 44), fill=(120, 200, 255, 255))   # inner core
    return img


def start_tray(on_stop: Callable[[], None], on_dashboard: Optional[Callable[[], None]] = None):
    """Start the tray icon in a daemon thread. Returns the icon, or None if unavailable."""
    try:
        import pystray
    except Exception:
        logger.info("[Tray] pystray not available — running without a tray icon.")
        return None

    def _stop(icon, _item):
        try:
            on_stop()
        finally:
            icon.stop()

    def _dashboard(_icon, _item):
        if on_dashboard:
            on_dashboard()

    menu = pystray.Menu(
        pystray.MenuItem("J.A.R.V.I.S.", None, enabled=False),
        pystray.MenuItem("Open Dashboard", _dashboard),
        pystray.MenuItem("Stop Jarvis", _stop),
    )
    icon = pystray.Icon("jarvis", _make_icon_image(), "J.A.R.V.I.S.", menu)

    threading.Thread(target=icon.run, name="jarvis-tray", daemon=True).start()
    logger.success("[Tray] System tray icon active.")
    return icon
