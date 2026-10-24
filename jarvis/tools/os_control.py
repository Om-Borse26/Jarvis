"""
J.A.R.V.I.S. — OS & Hardware Control Tools
Provides voice-accessible controls for:
  - System volume, mute, audio devices
  - Media playback (Play, Pause, Skip, Prev)
  - Power management (Lock, Sleep, Restart, Shutdown)
  - Display and desktop window minimization
"""
from __future__ import annotations

import ctypes
import subprocess
import pyautogui
from loguru import logger
from jarvis.tools.registry import register_tool

# Ensure PyAutoGUI failsafes don't crash long operations
pyautogui.FAILSAFE = False


@register_tool(name="set_volume", description="Set master system audio volume to a percentage (0 to 100).", category="audio")
def set_volume(percent: int) -> str:
    """Set master system audio volume to a percentage (0 to 100)."""
    try:
        import pycaw.pycaw as pycaw
        spk = pycaw.AudioUtilities.GetSpeakers()
        level = max(0.0, min(1.0, float(percent) / 100.0))
        spk.EndpointVolume.SetMasterVolumeLevelScalar(level, None)
        return f"Master volume set to {percent} percent."
    except Exception as e:
        logger.error(f"Set volume error: {e}")
        return f"Failed to set volume: {e}"


@register_tool(name="mute_volume", description="Mute the master system audio.", category="audio")
def mute_volume() -> str:
    """Mute the master system audio."""
    try:
        import pycaw.pycaw as pycaw
        spk = pycaw.AudioUtilities.GetSpeakers()
        spk.EndpointVolume.SetMute(1, None)
        return "Audio muted."
    except Exception as e:
        return f"Failed to mute: {e}"


@register_tool(name="unmute_volume", description="Unmute the master system audio.", category="audio")
def unmute_volume() -> str:
    """Unmute the master system audio."""
    try:
        import pycaw.pycaw as pycaw
        spk = pycaw.AudioUtilities.GetSpeakers()
        spk.EndpointVolume.SetMute(0, None)
        return "Audio unmuted."
    except Exception as e:
        return f"Failed to unmute: {e}"


@register_tool(name="get_volume", description="Check current master audio volume and mute status.", category="audio")
def get_volume() -> str:
    """Check current master audio volume and mute status."""
    try:
        import pycaw.pycaw as pycaw
        spk = pycaw.AudioUtilities.GetSpeakers()
        vol = round(spk.EndpointVolume.GetMasterVolumeLevelScalar() * 100)
        is_muted = bool(spk.EndpointVolume.GetMute())
        status = "muted" if is_muted else f"{vol} percent"
        return f"Volume is currently {status} on {spk.FriendlyName}."
    except Exception as e:
        return f"Failed to get volume: {e}"


@register_tool(name="media_play_pause", description="Toggle media playback (play or pause current video/music).", category="media")
def media_play_pause() -> str:
    """Toggle media playback (play or pause current video/music)."""
    pyautogui.press("playpause")
    return "Toggled media playback."


@register_tool(name="media_next_track", description="Skip to the next audio or video track.", category="media")
def media_next_track() -> str:
    """Skip to the next audio or video track."""
    pyautogui.press("nexttrack")
    return "Skipped to next track."


@register_tool(name="media_prev_track", description="Return to the previous audio or video track.", category="media")
def media_prev_track() -> str:
    """Return to the previous audio or video track."""
    pyautogui.press("prevtrack")
    return "Returned to previous track."


@register_tool(name="lock_workstation", description="Immediately lock the Windows PC session.", category="power")
def lock_workstation() -> str:
    """Immediately lock the Windows PC session."""
    ctypes.windll.user32.LockWorkStation()
    return "Workstation locked, Sir."


@register_tool(name="sleep_pc", description="Put the Windows computer into sleep / suspend mode.", category="power")
def sleep_pc() -> str:
    """Put the Windows computer into sleep / suspend mode."""
    subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0", "1", "0"], check=False)
    return "Putting computer to sleep, Sir."


@register_tool(name="show_desktop", description="Minimize all open windows and show the desktop (Win+D).", category="window")
def show_desktop() -> str:
    """Minimize all open windows and show the desktop (Win+D)."""
    pyautogui.hotkey("win", "d")
    return "Desktop displayed."
