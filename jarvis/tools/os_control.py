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


def _get_speakers():
    import pycaw.pycaw as pycaw
    spk = pycaw.AudioUtilities.GetSpeakers()
    if spk is None:
        raise RuntimeError("No audio output device found.")
    return spk


@register_tool(name="set_volume", description="Set master system audio volume to a percentage (0 to 100).", category="audio")
def set_volume(percent: int) -> str:
    """Set master system audio volume to a percentage (0 to 100)."""
    try:
        spk = _get_speakers()
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
        spk = _get_speakers()
        spk.EndpointVolume.SetMute(1, None)
        return "Audio muted."
    except Exception as e:
        return f"Failed to mute: {e}"


@register_tool(name="unmute_volume", description="Unmute the master system audio.", category="audio")
def unmute_volume() -> str:
    """Unmute the master system audio."""
    try:
        spk = _get_speakers()
        spk.EndpointVolume.SetMute(0, None)
        return "Audio unmuted."
    except Exception as e:
        return f"Failed to unmute: {e}"


@register_tool(name="get_volume", description="Check current master audio volume and mute status.", category="audio")
def get_volume() -> str:
    """Check current master audio volume and mute status."""
    try:
        spk = _get_speakers()
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


@register_tool(name="change_volume_relative", description="Increase or decrease master volume by a percentage delta (e.g. +10 or -10).", category="audio")
def change_volume_relative(delta_percent: int = 10) -> str:
    """Increase or decrease volume relative to current level."""
    try:
        spk = _get_speakers()
        cur_scalar = spk.EndpointVolume.GetMasterVolumeLevelScalar()
        new_scalar = max(0.0, min(1.0, cur_scalar + (float(delta_percent) / 100.0)))
        spk.EndpointVolume.SetMasterVolumeLevelScalar(new_scalar, None)
        vol_pct = round(new_scalar * 100)
        action = "increased" if delta_percent > 0 else "decreased"
        return f"Volume {action} to {vol_pct} percent, Sir."
    except Exception as e:
        logger.error(f"Relative volume error: {e}")
        return f"Failed to adjust volume: {e}"


@register_tool(name="set_brightness", description="Set the laptop screen brightness to a percentage (0 to 100).", category="system")
def set_brightness(percent: int) -> str:
    """Set the display brightness (0-100) via WMI."""
    level = max(0, min(100, percent))
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,{level})"],
            capture_output=True, timeout=5, check=True,
        )
        return f"Screen brightness set to {level} percent."
    except Exception as e:
        logger.error(f"Set brightness error: {e}")
        return "I couldn't change the brightness — this PC may not support software brightness control."


@register_tool(name="get_brightness", description="Check the current laptop screen brightness percentage.", category="system")
def get_brightness() -> str:
    """Read the current display brightness (0-100) via WMI."""
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightness).CurrentBrightness"],
            capture_output=True, text=True, timeout=5,
        )
        val = res.stdout.strip().splitlines()[0].strip() if res.stdout.strip() else ""
        if val.isdigit():
            return f"Screen brightness is at {val} percent."
        return "I couldn't read the brightness on this display."
    except Exception as e:
        logger.error(f"Get brightness error: {e}")
        return "I couldn't read the brightness on this display."


@register_tool(name="change_brightness_relative", description="Increase or decrease screen brightness by a percentage delta (e.g. +10 or -10).", category="system")
def change_brightness_relative(delta_percent: int = 10) -> str:
    """Adjust display brightness relative to its current level via WMI."""
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightness).CurrentBrightness"],
            capture_output=True, text=True, timeout=5,
        )
        cur = res.stdout.strip().splitlines()[0].strip() if res.stdout.strip() else ""
        if not cur.isdigit():
            return "I couldn't read the current brightness on this display."
        new_level = max(0, min(100, int(cur) + int(delta_percent)))
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,{new_level})"],
            capture_output=True, timeout=5, check=True,
        )
        action = "raised" if delta_percent > 0 else "lowered"
        return f"Brightness {action} to {new_level} percent, Sir."
    except Exception as e:
        logger.error(f"Relative brightness error: {e}")
        return "I couldn't adjust the brightness on this display."


@register_tool(name="get_current_active_window", description="Identify the currently focused application and active window title.", category="window")
def get_current_active_window() -> str:
    """Get active window title and process name."""
    try:
        import psutil
        import win32gui
        import win32process
        hwnd = win32gui.GetForegroundWindow()
        if hwnd:
            title = win32gui.GetWindowText(hwnd)
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc_name = ""
            try:
                proc_name = psutil.Process(pid).name()
            except Exception:
                pass
            if title and title.strip():
                return f"You are currently in '{title.strip()}' ({proc_name})."
    except Exception:
        pass
    return "You are currently in your active desktop workspace."


@register_tool(name="compose_email", description="Open Gmail in browser to compose a new mail or email without Windows modals.", category="system")
def compose_email(to: str = "", subject: str = "", body: str = "") -> str:
    """Open Gmail composer directly in default browser with zero Windows modals."""
    import urllib.parse
    params = ["view=cm", "fs=1"]
    if to:
        params.append(f"to={urllib.parse.quote(to)}")
    if subject:
        params.append(f"su={urllib.parse.quote(subject)}")
    if body:
        params.append(f"body={urllib.parse.quote(body)}")
    target = f"https://mail.google.com/mail/?{'&'.join(params)}"
    try:
        subprocess.Popen(f'start "" "{target}"', shell=True)
        return "Opening Gmail composer in your browser, Sir."
    except Exception as e:
        return f"Failed to open email composer: {e}"


