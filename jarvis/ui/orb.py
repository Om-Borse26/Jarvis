"""
J.A.R.V.I.S. — Orb Overlay Window
A frameless, transparent, always-on-top desktop orb that reflects Jarvis's state.
Runs as its own process (pywebview needs the main thread):  python -m jarvis.ui.orb

It parks itself in the bottom-right corner and becomes click-through when idle so
it never blocks what you're doing; it only intercepts the mouse while active.
"""
from __future__ import annotations

import sys
import threading
import time

from loguru import logger

_WIDTH = 240
_HEIGHT = 240


def _ui_port() -> int:
    try:
        from jarvis.core.config import load_config
        return int(load_config().get("ui", {}).get("http_port", 8787))
    except Exception:
        return 8787


def _make_click_through(enable: bool) -> None:
    """Toggle mouse click-through on the orb window (Windows only, best-effort)."""
    try:
        import win32gui
        import win32con
        hwnd = win32gui.FindWindow(None, "Jarvis Orb")
        if not hwnd:
            return
        style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        if enable:
            style |= win32con.WS_EX_TRANSPARENT  # clicks pass through
        else:
            style &= ~win32con.WS_EX_TRANSPARENT
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style)
    except Exception:
        pass


def _watch_state_for_clickthrough(port: int) -> None:
    """Make the orb click-through while idle, interactive while active."""
    import urllib.request
    last = None
    while True:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=2) as r:
                import json
                state = json.loads(r.read().decode("utf-8")).get("state", "idle")
            if state != last:
                _make_click_through(enable=(state == "idle"))
                last = state
        except Exception:
            pass
        time.sleep(0.4)


def run() -> None:
    try:
        import webview
    except Exception:
        logger.error("[Orb] pywebview is required for the orb window.")
        return

    port = _ui_port()
    try:
        screen = webview.screens[0] if getattr(webview, "screens", None) else None
    except Exception:
        screen = None

    window = webview.create_window(
        "Jarvis Orb",
        url=f"http://127.0.0.1:{port}/orb",
        width=_WIDTH,
        height=_HEIGHT,
        frameless=True,
        easy_drag=True,
        on_top=True,
        resizable=False,
        background_color="#0a0e1a",
    )

    def _position():
        try:
            if screen:
                window.move(screen.width - _WIDTH - 30, screen.height - _HEIGHT - 80)
            import win32gui
            hwnd = int(window.native.Handle.ToInt64())
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            region = win32gui.CreateEllipticRgn(0, 0, right - left, bottom - top)
            win32gui.SetWindowRgn(hwnd, region, True)
        except Exception:
            pass
        threading.Thread(target=_watch_state_for_clickthrough, args=(port,), daemon=True).start()

    window.events.loaded += _position
    webview.start(gui="edgechromium" if sys.platform == "win32" else None)


if __name__ == "__main__":
    run()
