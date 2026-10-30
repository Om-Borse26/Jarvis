"""
J.A.R.V.I.S. — Dynamic Island Window
A frameless, rounded "pill" docked at the top-center of the desktop that reflects
Jarvis's state and expands on demand. Runs as its own process (pywebview needs
the main thread):  python -m jarvis.ui.island

Design notes:
  • The window is clipped to a rounded-rectangle REGION (CreateRoundRectRgn), so
    there is no square/background even though WebView2 can't do true transparency
    — the visible pill is simply an opaque dark rounded shape (like Apple's).
  • Default z-order is NOT always-on-top and non-activating, so it sits on the
    desktop and gets covered when you focus apps. Voice ("come forward") raises it.
  • The web layer calls back into Python (window.pywebview.api.*) to resize/move
    the native window and change z-order as it morphs between modes.
"""
from __future__ import annotations

import sys
import threading
import time

from loguru import logger

# (width, height, corner-radius) per mode.
_MODES = {
    "collapsed": (380, 54, 27),
    "mini":      (470, 300, 24),
    "tools":     (470, 400, 24),
    "dashboard": (1180, 760, 18),
}
_TOP_MARGIN = 12


def _ui_port() -> int:
    try:
        from jarvis.core.config import load_config
        return int(load_config().get("ui", {}).get("http_port", 8787))
    except Exception:
        return 8787


class IslandApi:
    """Native bridge exposed to the web layer as window.pywebview.api."""

    def __init__(self) -> None:
        self.window = None
        self._screen_w = 1920
        self._screen_h = 1080

    # ── geometry ─────────────────────────────────────────────────────────
    def set_mode(self, mode: str) -> None:
        """Resize+recenter the native window for a UI mode and round its corners."""
        w, h, r = _MODES.get(mode, _MODES["collapsed"])
        try:
            x = max(0, (self._screen_w - w) // 2)
            y = _TOP_MARGIN if mode != "dashboard" else max(0, (self._screen_h - h) // 3)
            if self.window:
                self.window.resize(w, h)
                self.window.move(x, y)
            self._apply_region(w, h, r)
        except Exception as e:
            logger.debug(f"[Island] set_mode notice: {e}")

    def _hwnd(self):
        try:
            return int(self.window.native.Handle.ToInt64())
        except Exception:
            return None

    def _apply_region(self, w: int, h: int, r: int) -> None:
        try:
            import win32gui
            hwnd = self._hwnd()
            if not hwnd:
                return
            region = win32gui.CreateRoundRectRgn(0, 0, w + 1, h + 1, r * 2, r * 2)
            win32gui.SetWindowRgn(hwnd, region, True)
        except Exception as e:
            logger.debug(f"[Island] region notice: {e}")

    # ── z-order ──────────────────────────────────────────────────────────
    def come_forward(self) -> None:
        """Raise above other windows (topmost), without stealing keyboard focus."""
        try:
            import win32gui, win32con
            hwnd = self._hwnd()
            if hwnd:
                win32gui.SetWindowPos(
                    hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
                )
        except Exception as e:
            logger.debug(f"[Island] come_forward notice: {e}")

    def send_back(self) -> None:
        """Drop back to the desktop layer (not topmost)."""
        try:
            import win32gui, win32con
            hwnd = self._hwnd()
            if hwnd:
                win32gui.SetWindowPos(
                    hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
                )
        except Exception as e:
            logger.debug(f"[Island] send_back notice: {e}")


def _make_unobtrusive(hwnd) -> None:
    """No taskbar button, never steals focus on click (widget-like)."""
    try:
        import win32gui, win32con
        ex = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        ex |= win32con.WS_EX_NOACTIVATE | win32con.WS_EX_TOOLWINDOW
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex)
    except Exception:
        pass


def run() -> None:
    try:
        import webview
    except Exception:
        logger.error("[Island] pywebview is required for the island window.")
        return

    port = _ui_port()
    api = IslandApi()
    try:
        screen = webview.screens[0] if getattr(webview, "screens", None) else None
        if screen:
            api._screen_w, api._screen_h = screen.width, screen.height
    except Exception:
        screen = None

    w, h, r = _MODES["collapsed"]
    window = webview.create_window(
        "Jarvis Island",
        url=f"http://127.0.0.1:{port}/island",
        width=w,
        height=h,
        x=max(0, (api._screen_w - w) // 2),
        y=_TOP_MARGIN,
        frameless=True,
        easy_drag=False,          # dragging handled by the pill's own grab zone
        on_top=False,             # sits on the desktop by default
        resizable=False,
        background_color="#05070d",
        js_api=api,
    )
    api.window = window

    def _on_loaded():
        try:
            hwnd = api._hwnd()
            if hwnd:
                _make_unobtrusive(hwnd)
            api._apply_region(w, h, r)
            api.send_back()
        except Exception as e:
            logger.debug(f"[Island] init notice: {e}")

    window.events.loaded += _on_loaded
    webview.start(gui="edgechromium" if sys.platform == "win32" else None)


if __name__ == "__main__":
    run()
