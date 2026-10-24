"""
J.A.R.V.I.S. — Lightweight Launcher
A tiny always-on helper that makes Win+J behave like Windows Copilot's Win+C:

  - If Jarvis isn't running, Win+J launches it in the background.
  - If Jarvis is already running, its own in-process Win+J handles listening, so
    this launcher does nothing (it won't start a duplicate).

Put THIS in your Startup instead of main.py if you want Jarvis to stay dormant
until you press Win+J. Run with:  python -m jarvis.ui.launcher
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from loguru import logger

from jarvis.core.lifecycle import is_instance_running

_MAIN = Path(__file__).resolve().parents[2] / "main.py"


def _launch_jarvis() -> None:
    if is_instance_running():
        logger.info("[Launcher] Jarvis already running — Win+J handled in-process.")
        return
    py = sys.executable
    pyw = py.replace("python.exe", "pythonw.exe")
    exe = pyw if Path(pyw).exists() else py
    logger.info("[Launcher] Starting Jarvis…")
    creationflags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
    subprocess.Popen([exe, str(_MAIN)], creationflags=creationflags, cwd=str(_MAIN.parent))


def run() -> None:
    try:
        import keyboard
    except Exception:
        logger.error("[Launcher] The 'keyboard' package is required for the Win+J launcher.")
        return
    keyboard.add_hotkey("windows+j", _launch_jarvis, suppress=False)
    logger.success("[Launcher] Ready. Press Win+J to start Jarvis.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
