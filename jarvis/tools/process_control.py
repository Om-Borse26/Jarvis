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
import difflib
import json
import shutil
import subprocess
import winreg
from pathlib import Path
from typing import Optional, Tuple, List, Dict
import psutil
from loguru import logger
from jarvis.tools.registry import register_tool


def focus_existing_window(app_query: str) -> Optional[str]:
    """
    Check if an application window is already running and bring it to the foreground.
    Prevents spawning duplicate instances (e.g. cascading VS Code, Chrome, or Brave windows).
    """
    try:
        import ctypes
        import win32gui
        import win32con

        user32 = ctypes.windll.user32
        # Ensure thread is attached to the interactive user desktop
        hdesk = user32.OpenInputDesktop(0, False, 0x0100 | 0x0040)
        if hdesk:
            user32.SetThreadDesktop(hdesk)

        q = app_query.lower().strip()
        alias_map = {
            "vscode": ["visual studio code", " - code"],
            "vs code": ["visual studio code", " - code"],
            "code": ["visual studio code", " - code"],
            "vscod": ["visual studio code", " - code"],
            "viscode": ["visual studio code", " - code"],
            "brave": ["brave"],
            "chrome": ["google chrome", "chrome"],
            "edge": ["microsoft edge", "edge"],
            "notepad": ["notepad"],
            "blender": ["blender"],
            "discord": ["discord"],
            "whatsapp": ["whatsapp"],
            "spotify": ["spotify"],
            "explorer": ["file explorer", "this pc", "documents", "downloads"],
            "terminal": ["powershell", "windows terminal", "cmd"],
        }
        search_terms = alias_map.get(q, [q])

        matched_hwnds = []

        def enum_cb(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd).strip()
                t_lower = title.lower()
                for term in search_terms:
                    # Ignore our own IDE window if searching for separate VS Code
                    if term in ("visual studio code", " - code") and "antigravity" in t_lower:
                        continue
                    if term in t_lower:
                        matched_hwnds.append((hwnd, title))
                        break
            return True

        try:
            win32gui.EnumWindows(enum_cb, None)
        except Exception:
            pass

        if matched_hwnds:
            # If multiple VS Code windows are open (e.g. 1 workspace + empty Welcome ghost windows)
            if q in ("vscode", "vs code", "code", "vscod", "viscode") and len(matched_hwnds) > 1:
                real_ws = [w for w in matched_hwnds if w[1] != "Welcome - Visual Studio Code"]
                empty_ws = [w for w in matched_hwnds if w[1] == "Welcome - Visual Studio Code"]
                if real_ws and empty_ws:
                    for ehwnd, _ in empty_ws:
                        try:
                            user32.PostMessageW(ehwnd, win32con.WM_CLOSE, 0, 0)
                        except Exception:
                            pass
                    target_hwnd, matched_title = real_ws[0]
                elif empty_ws:
                    for ehwnd, _ in empty_ws[1:]:
                        try:
                            user32.PostMessageW(ehwnd, win32con.WM_CLOSE, 0, 0)
                        except Exception:
                            pass
                    target_hwnd, matched_title = empty_ws[0]
                else:
                    target_hwnd, matched_title = matched_hwnds[0]
            else:
                target_hwnd, matched_title = matched_hwnds[0]

            cur_fg = user32.GetForegroundWindow()
            cur_thread = user32.GetWindowThreadProcessId(cur_fg, None)
            my_thread = ctypes.windll.kernel32.GetCurrentThreadId()

            try:
                user32.AttachThreadInput(cur_thread, my_thread, True)
                user32.ShowWindow(target_hwnd, win32con.SW_RESTORE)
                user32.SetForegroundWindow(target_hwnd)
                user32.AttachThreadInput(cur_thread, my_thread, False)
            except Exception:
                win32gui.ShowWindow(target_hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(target_hwnd)

            return matched_title
    except Exception as e:
        logger.debug(f"Window focus notice: {e}")
    return None


class DynamicAppResolver:
    """
    Intelligent dynamic Windows application discovery and ranking engine.
    Eliminates hardcoded paths by scanning:
      1. User and System Start Menu shortcuts (.lnk)
      2. Windows Desktop shortcuts
      3. Windows Registry App Paths (HKLM & HKCU)
      4. Windows UWP / URI protocol handlers
      5. System PATH binaries
    """

    IGNORE_TERMS = {
        "uninstall", "remove", "setup", "install", "readme", "help",
        "documentation", "license", "website", "url", "updater",
        "troubleshooter", "release notes", "service", "crash", "handler"
    }

    UWP_PROTOCOLS: Dict[str, str] = {
        "whatsapp": "cmd /c start whatsapp:",
        "whats app": "cmd /c start whatsapp:",
        "spotify": "cmd /c start spotify:",
        "calculator": "calc.exe",
        "calc": "calc.exe",
        "terminal": "wt.exe",
        "cmd": "cmd.exe",
        "command prompt": "cmd.exe",
        "powershell": "powershell.exe",
        "notepad": "notepad.exe",
        "explorer": "explorer.exe",
        "file explorer": "explorer.exe",
        "settings": "cmd /c start ms-settings:",
        "camera": "cmd /c start microsoft.windows.camera:",
        "store": "cmd /c start ms-windows-store:",
    }

    def __init__(self, cache_file: str = "data/app_index.json") -> None:
        self.cache_file = Path(cache_file)
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self._apps: List[Tuple[str, str, str]] = []  # (name, path_or_target, source)
        self.refresh()

    def refresh(self) -> int:
        """Scan Windows filesystem and registry for all installed applications."""
        discovered: List[Tuple[str, str, str]] = []

        # 1. Start Menu & Desktops
        search_dirs = [
            Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
            Path("C:/ProgramData/Microsoft/Windows/Start Menu/Programs"),
            Path(os.environ.get("USERPROFILE", "")) / "Desktop",
            Path("C:/Users/Public/Desktop"),
        ]
        for d in search_dirs:
            if d.exists():
                try:
                    for f in d.rglob("*.lnk"):
                        discovered.append((f.stem, str(f), "shortcut"))
                except Exception:
                    pass

        # 2. Windows Registry App Paths (HKLM & HKCU)
        for root in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
            try:
                key = winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths")
                count = winreg.QueryInfoKey(key)[0]
                for i in range(count):
                    try:
                        sub = winreg.EnumKey(key, i)
                        sub_key = winreg.OpenKey(key, sub)
                        val, _ = winreg.QueryValueEx(sub_key, "")
                        winreg.CloseKey(sub_key)
                        if val and os.path.exists(val):
                            stem = Path(sub).stem
                            discovered.append((stem, val, "registry"))
                    except Exception:
                        pass
                winreg.CloseKey(key)
            except Exception:
                pass

        self._apps = discovered
        logger.debug(f"[APP_RESOLVER] Indexed {len(self._apps)} installed applications.")
        return len(self._apps)

    def resolve(self, query: str) -> Optional[Tuple[float, str, str, str]]:
        """
        Score and rank installed applications against the query.
        Returns (score, matched_name, target_path, source_type) or None.
        """
        q = query.lower().strip()
        if not q:
            return None

        # Check UWP / direct protocols first
        if q in self.UWP_PROTOCOLS:
            return (1.0, q, self.UWP_PROTOCOLS[q], "protocol")

        q_clean = q.replace("-", " ").replace("_", " ")
        q_tokens = set(q_clean.split())
        q_compact = q.replace(" ", "").replace("-", "").replace("_", "")

        scored: List[Tuple[float, str, str, str]] = []

        for stem, path, ctype in self._apps:
            stem_lower = stem.lower()
            if any(ign in stem_lower for ign in self.IGNORE_TERMS):
                continue

            stem_clean = stem_lower.replace("-", " ").replace("_", " ")
            stem_tokens = set(stem_clean.split())
            stem_compact = stem_lower.replace(" ", "").replace("-", "").replace("_", "")

            # Rule 1: Exact match
            if q == stem_lower or q_compact == stem_compact:
                score = 1.0
            # Rule 2: Token subset (e.g. 'code' in 'Visual Studio Code', or 'vs code')
            elif q_tokens.issubset(stem_tokens):
                score = 0.95
            # Rule 3: Acronym match (e.g. 'vscode' -> 'Visual Studio Code')
            elif "".join(w[0] for w in stem_clean.split() if w) == q_compact:
                score = 0.93
            # Rule 4: All query tokens appear as substrings of stem tokens
            elif all(any(qt in st for st in stem_tokens) for qt in q_tokens):
                score = 0.90
            # Rule 5: Substring containment
            elif q_compact in stem_compact:
                score = 0.85
            elif stem_compact in q_compact:
                score = 0.80
            # Rule 6: Fuzzy SequenceMatcher
            else:
                ratio = difflib.SequenceMatcher(None, q, stem_lower).ratio()
                score = ratio if ratio >= 0.55 else 0.0

            if score >= 0.50:
                # Slight preference for Start Menu shortcuts over raw registry paths
                adj_score = score + (0.02 if ctype == "shortcut" else 0.0)
                scored.append((adj_score, stem, path, ctype))

        if scored:
            scored.sort(key=lambda x: x[0], reverse=True)
            return scored[0]

        # Fallback: check PATH
        which_path = shutil.which(query) or shutil.which(f"{query}.exe")
        if which_path:
            return (0.75, query, which_path, "path")

        return None

    def launch(self, query: str, force_new: bool = False) -> str:
        """Find best application match, focusing existing window or launching if not running."""
        clean_q = query.lower().strip()

        # Step 1: Check if an open window already exists and reuse it!
        if not force_new and not any(kw in clean_q for kw in ["new window", "another instance", "new tab", "duplicate"]):
            existing_title = focus_existing_window(clean_q)
            if existing_title:
                logger.info(f"🔄 Reusing active window '{existing_title}' instead of spawning duplicate.")
                return f"Switched to your open {clean_q} window, Sir."

        match = self.resolve(query)
        if not match:
            return f"I could not find an application matching '{query}' installed on your PC, Sir."

        score, name, target, source = match
        try:
            if source == "protocol":
                if target.startswith("cmd /c"):
                    subprocess.Popen(target, shell=True)
                else:
                    subprocess.Popen(target)
                return f"Opening {name.title()}, Sir."
            elif source == "shortcut" and target.endswith(".lnk"):
                os.startfile(target)
                return f"Opening {name}, Sir."
            else:
                # Executable path
                if Path(target).exists():
                    os.startfile(target)
                else:
                    subprocess.Popen(f'"{target}"', shell=True)
                return f"Opening {name}, Sir."
        except Exception as e:
            logger.error(f"Error launching {name} ({target}): {e}")
            return f"Failed to open {name}: {e}"


# Global application resolver instance
app_resolver = DynamicAppResolver()


@register_tool(name="launch_application", description="Launch an application dynamically by name or bring active window to front if already open.", category="process")
def launch_application(app_name: str, force_new: bool = False) -> str:
    """Dynamically focus existing application window or launch if not running."""
    clean = app_name.lower().strip()
    return app_resolver.launch(clean, force_new=force_new)


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
