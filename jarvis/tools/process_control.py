"""
J.A.R.V.I.S. — Process Management & Hardware Telemetry Tools
Enables Jarvis to:
  - Launch any application by name
  - Terminate hung or running processes
  - List top active apps
  - Report live NVIDIA GPU temperature, VRAM usage, CPU, RAM, and Battery
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
import psutil
from loguru import logger
from jarvis.tools.registry import register_tool

# Common executable aliases for rapid launching
APP_ALIASES = {
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
    ],
    "discord": [
        os.path.expandvars(r"%LOCALAPPDATA%\Discord\Update.exe --processStart Discord.exe"),
    ],
    "vscode": [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
        r"C:\Program Files\Microsoft VS Code\Code.exe",
    ],
    "code": [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
    ],
    "notepad": ["notepad.exe"],
    "calc": ["calc.exe"],
    "calculator": ["calc.exe"],
    "explorer": ["explorer.exe"],
    "terminal": ["wt.exe", "powershell.exe"],
    "cmd": ["cmd.exe"],
    "powershell": ["powershell.exe"],
    "spotify": [
        os.path.expandvars(r"%APPDATA%\Spotify\Spotify.exe"),
    ],
}


@register_tool(name="launch_application", description="Launch an application by name (e.g. brave, blender, vscode, discord, notepad).", category="process")
def launch_application(app_name: str) -> str:
    """Launch an application by name."""
    clean = app_name.lower().strip()
    cmd = None

    if clean in APP_ALIASES:
        for candidate in APP_ALIASES[clean]:
            parts = candidate.split(" ")
            exe = parts[0]
            if Path(exe).exists() or shutil.which(exe):
                cmd = candidate
                break

    if not cmd:
        cmd = f'start "" "{clean}"'

    try:
        subprocess.Popen(cmd, shell=True)
        return f"Opening {app_name}, Sir."
    except Exception as e:
        return f"Failed to launch {app_name}: {e}"


@register_tool(name="kill_process", description="Terminate a running application or process by name (e.g. chrome, brave, blender).", category="process")
def kill_process(process_name: str) -> str:
    """Terminate a running process by name."""
    target = process_name.lower().strip()
    if not target.endswith(".exe"):
        target_exe = target + ".exe"
    else:
        target_exe = target

    killed = 0
    for proc in psutil.process_iter(['name']):
        try:
            p_name = proc.info['name']
            if p_name and (p_name.lower() == target_exe or target in p_name.lower()):
                proc.kill()
                killed += 1
        except Exception:
            pass

    if killed > 0:
        return f"Terminated {killed} instances of {process_name}."
    return f"No running process found matching '{process_name}'."


@register_tool(name="get_hardware_metrics", description="Get real-time NVIDIA GPU temperature, VRAM usage, CPU, RAM, and Battery telemetry.", category="system")
def get_hardware_metrics() -> str:
    """Get real-time NVIDIA GPU temperature, VRAM usage, CPU, RAM, and Battery telemetry."""
    # GPU
    gpu_info = "GPU: Integrated / Non-NVIDIA"
    try:
        res = subprocess.run(
            ['nvidia-smi', '--query-gpu=temperature.gpu,memory.used,memory.total,utilization.gpu', '--format=csv,noheader,nounits'],
            capture_output=True,
            text=True,
            timeout=2.0
        )
        if res.returncode == 0:
            temp, mem_used, mem_total, util = res.stdout.strip().split(',')
            gpu_info = f"RTX 4050 GPU at {float(temp.strip()):.0f}°C, {mem_used.strip()} MB of {mem_total.strip()} MB VRAM used ({util.strip()}% load)"
    except Exception as e:
        logger.debug(f"nvidia-smi notice: {e}")

    # CPU & RAM
    cpu = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()
    battery = psutil.sensors_battery()

    bat_str = f", Battery is at {battery.percent}%" if battery else ""
    return (
        f"{gpu_info}. "
        f"CPU is at {cpu:.0f}%, RAM usage is {mem.percent}% ({round(mem.available / (1024**3), 1)} GB free){bat_str}."
    )


@register_tool(name="list_active_apps", description="List names of major applications currently running on your PC.", category="process")
def list_active_apps() -> str:
    """List names of major applications currently running on your PC."""
    apps = set()
    for p in psutil.process_iter(['name']):
        try:
            n = p.info['name']
            if n and n.lower().endswith('.exe'):
                base = n[:-4].lower()
                if base in ['code', 'brave', 'chrome', 'discord', 'blender', 'spotify', 'notepad', 'windowsterminal', 'powershell', 'cmd']:
                    apps.add(base)
        except Exception:
            pass
    if not apps:
        return "No major foreground applications running."
    return f"Currently running applications: {', '.join(sorted(list(apps)))}."
