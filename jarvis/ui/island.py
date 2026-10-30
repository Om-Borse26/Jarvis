"""
J.A.R.V.I.S. — Dynamic Island Window
A frameless, rounded "pill" docked at the top-center of the desktop that reflects
Jarvis's state and expands on demand. Runs as its own process (pywebview needs
the main thread):  python -m jarvis.ui.island

Design notes:
  • The window is clipped to a rounded-rectangle REGION, so there is no square
    background even though WebView2 can't do true transparency.
  • Default z-order is the bottom of the stack (sits on the desktop, covered by
    apps). Voice ("come forward") or hovering raises it.
  • Freeze-safety: pywebview exposes every PUBLIC attribute of the js_api object
    to JavaScript, and runs each bridge call on its own thread. So IslandApi has
    NO public attributes, and its methods only enqueue a request and return
    immediately. A single worker thread applies geometry/z-order with raw Win32
    calls (SWP_ASYNCWINDOWPOS posts to the UI thread instead of blocking it).
"""
from __future__ import annotations

import queue
import sys
import threading

from loguru import logger

_TITLE = "Jarvis Island"

# (width, height, corner-radius) per mode, in logical (96-DPI) pixels.
MODES = {
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


def compute_geometry(mode: str, screen_w: int, screen_h: int, scale: float = 1.0):
    """Pure: physical (x, y, w, h, radius) for a mode, centered horizontally."""
    w, h, r = MODES.get(mode, MODES["collapsed"])
    w, h, r = int(w * scale), int(h * scale), int(r * scale)
    w, h = min(w, screen_w), min(h, screen_h)
    x = max(0, (screen_w - w) // 2)
    if mode == "dashboard":
        y = max(0, (screen_h - h) // 3)
    else:
        y = int(_TOP_MARGIN * scale)
    return x, y, w, h, r


class _NativeWorker:
    """Applies window geometry / z-order off the UI and bridge threads."""

    def __init__(self) -> None:
        self._q: "queue.Queue[tuple]" = queue.Queue()
        threading.Thread(target=self._run, name="island-native", daemon=True).start()

    def submit(self, kind: str, value: str) -> None:
        self._q.put((kind, value))

    def _run(self) -> None:
        while True:
            kind, value = self._q.get()
            # Coalesce bursts (hover in/out) so only the latest request is applied.
            latest = {kind: value}
            try:
                while True:
                    k, v = self._q.get_nowait()
                    latest[k] = v
            except queue.Empty:
                pass
            try:
                if "mode" in latest:
                    self._apply_mode(latest["mode"])
                if "z" in latest:
                    self._apply_z(latest["z"])
            except Exception as e:
                logger.debug(f"[Island] native notice: {e}")

    @staticmethod
    def _hwnd():
        import win32gui
        return win32gui.FindWindow(None, _TITLE) or None

    @staticmethod
    def _scale(hwnd) -> float:
        try:
            import ctypes
            dpi = ctypes.windll.user32.GetDpiForWindow(hwnd)
            return (dpi or 96) / 96.0
        except Exception:
            return 1.0

    def _apply_mode(self, mode: str) -> None:
        import win32api, win32con, win32gui
        hwnd = self._hwnd()
        if not hwnd:
            return
        sw = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        sh = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
        x, y, w, h, r = compute_geometry(mode, sw, sh, self._scale(hwnd))
        flags = win32con.SWP_NOACTIVATE | win32con.SWP_NOZORDER | 0x4000  # SWP_ASYNCWINDOWPOS
        win32gui.SetWindowPos(hwnd, 0, x, y, w, h, flags)
        region = win32gui.CreateRoundRectRgn(0, 0, w + 1, h + 1, r * 2, r * 2)
        win32gui.SetWindowRgn(hwnd, region, True)

    def _apply_z(self, where: str) -> None:
        import win32con, win32gui
        hwnd = self._hwnd()
        if not hwnd:
            return
        flags = win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE | 0x4000
        if where == "front":
            win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, flags)
        else:
            win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0, flags)
            win32gui.SetWindowPos(hwnd, win32con.HWND_BOTTOM, 0, 0, 0, 0, flags)

    def hide_from_taskbar(self) -> None:
        try:
            import win32con, win32gui
            hwnd = self._hwnd()
            if hwnd:
                ex = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
                win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex | win32con.WS_EX_TOOLWINDOW)
        except Exception as e:
            logger.debug(f"[Island] taskbar notice: {e}")


class IslandApi:
    """JS bridge (window.pywebview.api). No public attributes — see module notes."""

    def __init__(self, worker: _NativeWorker) -> None:
        self._worker = worker

    def set_mode(self, mode: str) -> bool:
        if mode in MODES:
            self._worker.submit("mode", mode)
        return True

    def come_forward(self) -> bool:
        self._worker.submit("z", "front")
        return True

    def send_back(self) -> bool:
        self._worker.submit("z", "back")
        return True


def run() -> None:
    try:
        import webview
    except Exception:
        logger.error("[Island] pywebview is required for the island window.")
        return

    port = _ui_port()
    worker = _NativeWorker()
    api = IslandApi(worker)

    w, h, _ = MODES["collapsed"]
    try:
        screen = webview.screens[0] if getattr(webview, "screens", None) else None
        screen_w = screen.width if screen else 1920
    except Exception:
        screen_w = 1920

    window = webview.create_window(
        _TITLE,
        url=f"http://127.0.0.1:{port}/island",
        width=w,
        height=h,
        x=max(0, (screen_w - w) // 2),
        y=_TOP_MARGIN,
        frameless=True,
        easy_drag=False,
        on_top=False,
        resizable=False,
        background_color="#05070d",
        js_api=api,
    )

    def _on_loaded():
        worker.hide_from_taskbar()
        worker.submit("mode", "collapsed")
        worker.submit("z", "back")

    window.events.loaded += _on_loaded
    webview.start(gui="edgechromium" if sys.platform == "win32" else None)


if __name__ == "__main__":
    run()
