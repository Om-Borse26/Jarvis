"""
J.A.R.V.I.S. — HUD Overlay Window
A frameless, transparent, always-on-top, click-through overlay that shows
notifications and the confirmation safety gate. Runs as its own process
(pywebview needs the main thread):  python -m jarvis.hud.window

The overlay is click-through except when a confirmation card is showing, so it
never blocks your work — but you can still click Approve/Decline when it matters.
"""
from __future__ import annotations

import threading
import time
import sys

from loguru import logger


def _ui_port() -> int:
    try:
        from jarvis.core.config import load_config
        return int(load_config().get("ui", {}).get("http_port", 8787))
    except Exception:
        return 8787


def _set_click_through(enable: bool) -> None:
    try:
        import win32gui
        import win32con
        hwnd = win32gui.FindWindow(None, "Jarvis HUD")
        if not hwnd:
            return
        style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        if enable:
            style |= win32con.WS_EX_TRANSPARENT
        else:
            style &= ~win32con.WS_EX_TRANSPARENT
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style)
    except Exception:
        pass


def _watch(port: int, window) -> None:
    """Allow clicks only while a confirmation is showing; otherwise pass through."""
    import json
    import urllib.request
    last = None
    visible = False
    while True:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/hud", timeout=2) as r:
                data = json.loads(r.read().decode("utf-8"))
            interactive = data.get("confirmation") is not None
            should_show = interactive or bool(data.get("notifications"))
            if should_show != visible:
                window.show() if should_show else window.hide()
                visible = should_show
            if interactive != last:
                _set_click_through(enable=not interactive)
                last = interactive
        except Exception:
            pass
        time.sleep(0.4)


def run() -> None:
    try:
        import webview
    except Exception:
        logger.error("[HUD] pywebview is required for the HUD overlay.")
        return

    port = _ui_port()
    try:
        screen = webview.screens[0] if getattr(webview, "screens", None) else None
        width = screen.width if screen else 1280
        height = screen.height if screen else 800
    except Exception:
        width, height = 1280, 800

    window = webview.create_window(
        "Jarvis HUD",
        url=f"http://127.0.0.1:{port}/hud",
        width=400,
        height=240,
        x=width - 420,
        y=20,
        frameless=True,
        on_top=True,
        hidden=True,
        resizable=False,
        background_color="#10182c",
    )
    webview.start(lambda: _watch(port, window), gui="edgechromium" if sys.platform == "win32" else None)


if __name__ == "__main__":
    run()
