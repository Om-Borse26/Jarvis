"""
J.A.R.V.I.S. — Process Lifecycle
Keeps Jarvis to a single background instance and lets it shut itself down on
command ("Jarvis, turn yourself off").

- Single instance: a Windows named mutex (falls back to a PID lock file) so a
  second launch won't start a duplicate — it just exits.
- Self-shutdown: a process-wide event the pipeline watches; the stop_jarvis tool
  (and the tray/Win+J launcher) sets it for a clean exit.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

from loguru import logger

from jarvis.tools.registry import register_tool

_MUTEX_NAME = "Global\\JARVIS_Singleton_Mutex"
_LOCK_FILE = Path("data/.jarvis.lock")

_mutex_handle = None
_shutdown = threading.Event()


# ─── Single instance ──────────────────────────────────────────────────────────

def acquire_single_instance() -> bool:
    """Return True if this is the only Jarvis instance; False if one already runs."""
    global _mutex_handle
    # Preferred: Windows named mutex.
    try:
        import win32event
        import win32api
        import winerror
        _mutex_handle = win32event.CreateMutex(None, False, _MUTEX_NAME)
        if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
            return False
        return True
    except Exception:
        pass

    # Fallback: PID lock file.
    try:
        if _LOCK_FILE.exists():
            pid = int(_LOCK_FILE.read_text(encoding="utf-8").strip() or "0")
            if pid and _pid_alive(pid):
                return False
        _LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        _LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
        return True
    except Exception as e:
        logger.debug(f"[Lifecycle] single-instance check failed, allowing start: {e}")
        return True


def _pid_alive(pid: int) -> bool:
    try:
        import psutil
        return psutil.pid_exists(pid)
    except Exception:
        return False


def release_single_instance() -> None:
    try:
        if _LOCK_FILE.exists():
            _LOCK_FILE.unlink()
    except Exception:
        pass


def is_instance_running() -> bool:
    """Check (without acquiring) whether a Jarvis instance is already running."""
    try:
        import win32event
        import winerror
        import win32api
        handle = win32event.OpenMutex(0x00100000, False, _MUTEX_NAME)  # SYNCHRONIZE
        if handle:
            win32api.CloseHandle(handle)
            return True
    except Exception:
        pass
    # Fallback: PID lock file.
    try:
        if _LOCK_FILE.exists():
            pid = int(_LOCK_FILE.read_text(encoding="utf-8").strip() or "0")
            return bool(pid and _pid_alive(pid))
    except Exception:
        pass
    return False


# ─── Windows startup registration ─────────────────────────────────────────────

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE = "Jarvis"


def _startup_command() -> str:
    """Command that launches Jarvis in the background (pythonw, no console)."""
    import sys
    py = sys.executable
    pyw = py.replace("python.exe", "pythonw.exe")
    exe = pyw if Path(pyw).exists() else py
    main_py = Path(__file__).resolve().parents[2] / "main.py"
    return f'"{exe}" "{main_py}"'


def enable_startup() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, _RUN_VALUE, 0, winreg.REG_SZ, _startup_command())
        return True
    except Exception as e:
        logger.error(f"[Lifecycle] enable_startup failed: {e}")
        return False


def disable_startup() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, _RUN_VALUE)
        return True
    except FileNotFoundError:
        return True
    except Exception as e:
        logger.error(f"[Lifecycle] disable_startup failed: {e}")
        return False


def is_startup_enabled() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ) as k:
            winreg.QueryValueEx(k, _RUN_VALUE)
        return True
    except Exception:
        return False


# ─── Shutdown signalling ──────────────────────────────────────────────────────

def request_shutdown() -> None:
    _shutdown.set()


def shutdown_requested() -> bool:
    return _shutdown.is_set()


@register_tool(
    name="stop_jarvis",
    description="Shut Jarvis down completely and stop running. Use when the user says to turn you off, stop, shut down, or exit.",
    category="system",
)
def stop_jarvis() -> str:
    """Signal a clean shutdown of the whole assistant."""
    request_shutdown()
    return "Shutting down now. Goodbye."


@register_tool(
    name="enable_startup",
    description="Make Jarvis start automatically in the background when Windows starts.",
    category="system",
)
def enable_startup_tool() -> str:
    """Register Jarvis to launch at Windows startup."""
    return "Jarvis will now start automatically when Windows boots." if enable_startup() else "I couldn't enable startup."


@register_tool(
    name="disable_startup",
    description="Stop Jarvis from starting automatically when Windows starts.",
    category="system",
)
def disable_startup_tool() -> str:
    """Remove Jarvis from Windows startup."""
    return "Jarvis will no longer start automatically at boot." if disable_startup() else "I couldn't disable startup."
