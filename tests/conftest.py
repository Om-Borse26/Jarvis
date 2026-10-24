"""
Pytest configuration for J.A.R.V.I.S. logic tests.

The full app depends on Windows/GPU libraries (pywin32, pyautogui, torch,
faster-whisper, etc.) that aren't needed to test pure logic. This conftest
installs lightweight stand-ins for those *infrastructure* modules so the logic
modules import in any environment. Optional capabilities that the code already
guards with try/except (cryptography, win32crypt, ollama runtime, easyocr, …)
are intentionally NOT stubbed, so tests exercise the real graceful-degradation
paths. In your full `uv sync` environment the real libraries are present and
these stand-ins simply shadow unused infra.
"""
import sys
import types
from unittest.mock import MagicMock

# Infra modules imported unguarded at module top-level somewhere in the app.
_STUB_TOPLEVEL = {
    "win32gui", "win32con", "win32api", "win32process", "win32event",
    "win32clipboard", "win32com", "win32comext", "winerror", "pythoncom", "pywintypes",
    "pyautogui", "pyperclip", "psutil", "comtypes", "pycaw", "send2trash",
    "keyboard", "pynput", "pygetwindow", "mss", "PIL", "ollama",
    "sounddevice", "soundfile", "librosa", "faster_whisper",
    "kokoro_onnx", "kokoro", "onnxruntime", "torch", "torchaudio",
}


class _StubModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return MagicMock()


def _install_stubs():
    for name in _STUB_TOPLEVEL:
        if name in sys.modules:
            continue
        try:
            __import__(name)          # prefer the real module if present
        except Exception:
            sys.modules[name] = _StubModule(name)


_install_stubs()
