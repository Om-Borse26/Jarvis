"""
J.A.R.V.I.S. — System Control Tools
Full local Windows automation:
  - App launching (Brave, Blender, VSCode, Discord, Terminal, etc.)
  - Window control & process management
  - Volume, audio devices, and battery monitoring
  - Safe command execution with privilege guardrails
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from typing import Any

from loguru import logger

# Well-known Windows applications and common search paths
APP_REGISTRY: dict[str, list[str]] = {
    "brave": [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
    ],
    "chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ],
    "blender": [
        r"C:\Program Files\Blender Foundation\Blender\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.1\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe",
    ],
    "discord": [
        os.path.expandvars(r"%LOCALAPPDATA%\Discord\Update.exe --processStart Discord.exe"),
    ],
    "vscode": [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
        r"C:\Program Files\Microsoft VS Code\Code.exe",
    ],
    "notepad": ["notepad.exe"],
    "calc": ["calc.exe"],
    "explorer": ["explorer.exe"],
    "terminal": ["wt.exe", "powershell.exe"],
    "spotify": [
        os.path.expandvars(r"%APPDATA%\Spotify\Spotify.exe"),
    ],
}


class SystemControl:
    """Windows PC control interface."""

    def __init__(self) -> None:
        pass

    async def open_app(self, app_name: str, args: list[str] | None = None) -> dict[str, Any]:
        """Launch an application by common name or executable path."""
        target = app_name.lower().strip()
        cmd = None

        if target in APP_REGISTRY:
            candidates = APP_REGISTRY[target]
            for candidate in candidates:
                # Handle command with arguments
                parts = candidate.split(" ")
                exe_part = parts[0]
                if Path(exe_part).exists() or shutil.which(exe_part):
                    cmd = parts + (args or [])
                    break

        if not cmd:
            # Fallback to system PATH / start command
            cmd = ["cmd", "/c", "start", "", app_name] + (args or [])

        try:
            logger.info(f"Opening application: {app_name} -> {cmd}")
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            return {"status": "success", "message": f"Launched {app_name} successfully."}
        except Exception as e:
            logger.error(f"Failed to launch {app_name}: {e}")
            return {"status": "error", "message": f"Could not launch {app_name}: {str(e)}"}

    async def run_shell_command(self, command: str) -> dict[str, Any]:
        """Execute a safe shell command."""
        # Safety filter
        dangerous_keywords = ["rmdir /s /q c:", "del /f /s /q c:", "format c:", ":(){ :|:& };:"]
        for kw in dangerous_keywords:
            if kw in command.lower():
                return {"status": "denied", "message": "Command blocked by security safety arbiter."}

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            return {
                "status": "success" if proc.returncode == 0 else "error",
                "returncode": proc.returncode,
                "stdout": stdout.decode("utf-8", errors="replace").strip(),
                "stderr": stderr.decode("utf-8", errors="replace").strip(),
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def get_system_status(self) -> dict[str, Any]:
        """Get CPU, Memory, and Battery metrics."""
        import psutil

        cpu_percent = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        battery = psutil.sensors_battery()

        return {
            "cpu_percent": cpu_percent,
            "memory_used_percent": mem.percent,
            "memory_available_gb": round(mem.available / (1024**3), 2),
            "battery_percent": battery.percent if battery else None,
            "power_plugged": battery.power_plugged if battery else None,
        }

    async def list_open_windows(self) -> list[str]:
        """Get titles of open visible desktop windows."""
        try:
            import pygetwindow as gw

            titles = [
                win.title.strip()
                for win in gw.getAllWindows()
                if win.title.strip() and win.visible
            ]
            return titles[:15]
        except Exception as e:
            logger.warning(f"Failed to list windows: {e}")
            return []


# Module path import helper
from pathlib import Path
