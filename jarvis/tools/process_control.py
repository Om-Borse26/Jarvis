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


# Window title search terms per spoken app name (shared by the finder/focus helpers).
WINDOW_ALIAS_MAP = {
    "vscode": ["visual studio code", " - code"],
    "vs code": ["visual studio code", " - code"],
    "code": ["visual studio code", " - code"],
    "vscod": ["visual studio code", " - code"],
    "viscode": ["visual studio code", " - code"],
    "brave": ["brave"],
    "chrome": ["google chrome", "chrome"],
    "edge": ["microsoft edge", "edge"],
    "notepad": ["notepad", "untitled"],
    "blender": ["blender"],
    "discord": ["discord"],
    "whatsapp": ["whatsapp"],
    "spotify": ["spotify"],
    "explorer": ["file explorer", "this pc", "documents", "downloads"],
    "terminal": ["powershell", "windows terminal", "cmd"],
}

# Pretty spoken labels per app.
_APP_LABELS = {
    "vscode": "VS Code", "vs code": "VS Code", "code": "VS Code",
    "brave": "Brave", "chrome": "Chrome", "edge": "Edge",
    "notepad": "Notepad", "blender": "Blender", "discord": "Discord",
    "whatsapp": "WhatsApp", "spotify": "Spotify", "explorer": "File Explorer",
    "terminal": "the terminal",
}


def _app_label(app_query: str) -> str:
    q = (app_query or "").lower().strip()
    return _APP_LABELS.get(q, (app_query or "").strip().title() or "that app")


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
        hdesk = user32.OpenInputDesktop(0, False, 0x0100 | 0x0040 | 0x0001 | 0x0002)
        if hdesk:
            user32.SetThreadDesktop(hdesk)

        q = app_query.lower().strip()
        search_terms = WINDOW_ALIAS_MAP.get(q, [q])

        matched_hwnds = []

        def enum_cb(hwnd, _):
            try:
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
            except Exception:
                pass
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
            if _bring_to_front(target_hwnd):
                return matched_title
            return None
    except Exception as e:
        logger.debug(f"Window focus notice: {e}")
    return None


def find_app_window(app_query: str):
    """
    Return (hwnd, title, is_foreground) for a matching visible window, or None.
    Unlike focus_existing_window, this NEVER changes focus — it only inspects.
    """
    try:
        import ctypes
        import win32gui

        user32 = ctypes.windll.user32
        hdesk = user32.OpenInputDesktop(0, False, 0x0100 | 0x0040 | 0x0001 | 0x0002)
        if hdesk:
            user32.SetThreadDesktop(hdesk)

        q = (app_query or "").lower().strip()
        terms = WINDOW_ALIAS_MAP.get(q, [q])
        matches: List[Tuple[int, str]] = []

        def _cb(hwnd, _):
            try:
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd).strip()
                    tl = title.lower()
                    for term in terms:
                        if term in ("visual studio code", " - code") and "antigravity" in tl:
                            continue
                        if term and term in tl:
                            matches.append((hwnd, title))
                            break
            except Exception:
                pass
            return True

        try:
            win32gui.EnumWindows(_cb, None)
        except Exception:
            pass
        if not matches:
            return None
        hwnd, title = matches[0]
        try:
            is_fg = bool(user32.GetForegroundWindow() == hwnd)
        except Exception:
            is_fg = False
        return hwnd, title, is_fg
    except Exception as e:
        logger.debug(f"find_app_window notice: {e}")
        return None


def is_app_open(app_query: str) -> bool:
    """True if a visible window for the app exists. Does NOT change focus."""
    return find_app_window(app_query) is not None


def _bring_to_front(hwnd) -> bool:
    """Force a window to the foreground using the AttachThreadInput + Alt-key unlock."""
    try:
        import ctypes
        import win32con
        import win32gui

        user32 = ctypes.windll.user32
        # Unlock Windows SetForegroundWindow restriction by simulating Alt key tap
        try:
            user32.keybd_event(0x12, 0, 0, 0)  # VK_MENU down
            user32.keybd_event(0x12, 0, 2, 0)  # VK_MENU up
        except Exception:
            pass

        cur_fg = user32.GetForegroundWindow()
        cur_thread = user32.GetWindowThreadProcessId(cur_fg, None)
        my_thread = ctypes.windll.kernel32.GetCurrentThreadId()
        try:
            user32.AttachThreadInput(cur_thread, my_thread, True)
            user32.ShowWindow(hwnd, win32con.SW_RESTORE)
            user32.SetForegroundWindow(hwnd)
            user32.BringWindowToTop(hwnd)
            user32.AttachThreadInput(cur_thread, my_thread, False)
        except Exception:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
            win32gui.BringWindowToTop(hwnd)
        return True
    except Exception as e:
        logger.debug(f"bring_to_front notice: {e}")
        return False


def _get_foreground_hwnd():
    """Return the current foreground window handle, or None."""
    try:
        import ctypes
        return ctypes.windll.user32.GetForegroundWindow()
    except Exception:
        return None


def _reclaim_focus_in_background(prev_hwnd, app_query: str,
                                 attempts: int = 8, interval: float = 0.35) -> None:
    """
    After launching an app that grabs the foreground, hand focus back to the
    window the user was on. Only reclaims *from the app we just launched* — if
    the user intentionally switched to something else, we leave them alone.

    Best-effort: a brief flicker is possible because Windows' foreground-lock
    lets a launching app steal focus before we can restore it.
    """
    import time
    if not prev_hwnd:
        return
    try:
        import ctypes
        import win32gui
        user32 = ctypes.windll.user32
        for _ in range(attempts):
            time.sleep(interval)
            cur = user32.GetForegroundWindow()
            if cur == prev_hwnd:
                continue
            win = find_app_window(app_query)
            # Reclaim only if the freshly launched app is what holds focus.
            if win and cur == win[0]:
                if win32gui.IsWindow(prev_hwnd) and win32gui.IsWindowVisible(prev_hwnd):
                    _bring_to_front(prev_hwnd)
    except Exception as e:
        logger.debug(f"reclaim focus notice: {e}")


def _launch_background(prev_hwnd, app_query: str) -> None:
    """Spawn a daemon thread that keeps the user's window in focus after launch."""
    if not prev_hwnd:
        return
    import threading
    threading.Thread(
        target=_reclaim_focus_in_background,
        args=(prev_hwnd, app_query),
        daemon=True,
    ).start()


def decide_focus_message(label: str, found: bool, is_foreground: bool) -> str:
    """
    Pure focus-decision logic (unit-testable, no win32):
      - not open      -> "<label> isn't open, Sir."
      - already front -> "You're already on <label>, Sir."
      - otherwise     -> "Switched to <label>, Sir."
    """
    if not found:
        return f"{label} isn't open, Sir."
    if is_foreground:
        return f"You're already on {label}, Sir."
    return f"Switched to {label}, Sir."


@register_tool(
    name="focus_application",
    description="Bring an already-open application to the front (focus/switch/show). Reports if it isn't open or is already focused; NEVER launches a new instance. Use for 'switch to X', 'focus on X', 'show me X'.",
    category="process",
)
def focus_application(app_name: str) -> str:
    """Focus/switch to an open app with smart rules (not open / already focused / switch)."""
    label = _app_label(app_name)
    win = find_app_window(app_name)
    if not win:
        return decide_focus_message(label, found=False, is_foreground=False)
    hwnd, _title, is_fg = win
    if is_fg:
        return decide_focus_message(label, found=True, is_foreground=True)
    _bring_to_front(hwnd)
    return decide_focus_message(label, found=True, is_foreground=False)


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
        "calculator": r"C:\Windows\System32\calc.exe",
        "calc": r"C:\Windows\System32\calc.exe",
        "terminal": "cmd /c start wt",
        "cmd": r"C:\Windows\System32\cmd.exe",
        "command prompt": r"C:\Windows\System32\cmd.exe",
        "powershell": r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        "notepad": r"C:\Windows\System32\notepad.exe",
        "explorer": r"C:\Windows\explorer.exe",
        "file explorer": r"C:\Windows\explorer.exe",
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

    def launch(self, query: str, force_new: bool = False, background: bool = False) -> str:
        """Find best application match, focusing existing window or launching if not running.

        background=False (default) brings the launched app to the foreground;
        set background=True only if caller explicitly requests background mode.
        """
        clean_q = query.lower().strip()
        from jarvis.core.rules_engine import rules_engine

        # Step 1: Check if an open window already exists and reuse it!
        if rules_engine.should_reuse_window(clean_q, force_new):
            win = find_app_window(clean_q)
            if win:
                if not background:
                    _bring_to_front(win[0])
                    return f"Switched to {_app_label(clean_q)}, Sir."
                logger.info(f"🔄 '{win[1]}' already open — leaving it in the background (no focus steal).")
                label = _app_label(clean_q)
                return f"{label} is already open, Sir. Say 'switch to {label}' to bring it up."

            # Check if process is already running with an open window
            if is_app_open(clean_q):
                win = find_app_window(clean_q)
                if win and not background:
                    _bring_to_front(win[0])
                    return f"Switched to {_app_label(clean_q)}, Sir."
                label = _app_label(clean_q)
                return f"{label} is already open, Sir. Say 'switch to {label}' to bring it up."

        match = self.resolve(query)
        if not match:
            return f"I could not find an application matching '{query}' installed on your PC, Sir."

        score, name, target, source = match
        # Remember the window the user is on so we can hand focus back after launch.
        prev_hwnd = _get_foreground_hwnd() if background else None
        suffix = " in the background" if background else ""
        try:
            if target.startswith("cmd /c start "):
                subprocess.Popen(target, shell=True)
            elif Path(target).exists():
                os.startfile(target)
            elif source == "protocol" and not target.endswith(".exe"):
                subprocess.Popen(target, shell=True)
            else:
                try:
                    os.startfile(target)
                except Exception:
                    subprocess.Popen(f'"{target}"', shell=True)
            if background:
                _launch_background(prev_hwnd, clean_q)
            return f"Opening {name.title()}{suffix}, Sir."
        except Exception as e:
            logger.error(f"Error launching {name} ({target}): {e}")
            return f"Failed to open {name}: {e}"


# Global application resolver instance
app_resolver = DynamicAppResolver()


@register_tool(name="launch_application", description="Launch an application by name and bring it to the front. Set background=True only if the user explicitly asks for it to stay in the background.", category="process")
def launch_application(app_name: str, force_new: bool = False, background: bool = False) -> str:
    """Dynamically focus existing application window or launch if not running."""
    clean = app_name.lower().strip()
    return app_resolver.launch(clean, force_new=force_new, background=background)


@register_tool(name="kill_process", description="Terminate a running application or process by name (e.g. chrome, brave, blender, vs code, vscode).", category="process")
def kill_process(process_name: str) -> str:
    """
    Terminate a running application by name.
    Uses the global PROCESS_NAME_MAP for intelligent name resolution:
      "close vs code" → kills Code.exe
      "close brave" → kills brave.exe
      "close discord" → kills Discord.exe
    Attempts graceful WM_CLOSE first, then force kills if needed.
    """
    from jarvis.core.rules_engine import rules_engine

    target = process_name.lower().strip()
    # Resolve spoken name to actual process name
    target_exe = rules_engine.resolve_process_name(target)
    target_exe_lower = target_exe.lower()

    # Also match without .exe for fuzzy matching
    target_base = target_exe_lower.replace(".exe", "")

    # Step 1: Try graceful close via WM_CLOSE on windows
    graceful_closed = 0
    try:
        import ctypes
        import win32gui
        import win32con

        user32 = ctypes.windll.user32
        hdesk = user32.OpenInputDesktop(0, False, 0x0100 | 0x0040)
        if hdesk:
            user32.SetThreadDesktop(hdesk)

        def close_cb(hwnd, _):
            nonlocal graceful_closed
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd).lower()
                # Match by known window title patterns
                title_matches = {
                    "code.exe": ["visual studio code", " - code"],
                    "brave.exe": ["brave"],
                    "chrome.exe": ["google chrome", "chrome"],
                    "msedge.exe": ["microsoft edge", "edge"],
                    "discord.exe": ["discord"],
                    "spotify.exe": ["spotify"],
                    "blender.exe": ["blender"],
                }
                patterns = title_matches.get(target_exe_lower, [target_base])
                for pat in patterns:
                    if pat in title and "antigravity" not in title:
                        try:
                            user32.PostMessageW(hwnd, win32con.WM_CLOSE, 0, 0)
                            graceful_closed += 1
                        except Exception:
                            pass
                        break
            return True

        win32gui.EnumWindows(close_cb, None)
    except Exception as e:
        logger.debug(f"Graceful close notice: {e}")

    # Give windows time to exit gracefully
    if graceful_closed > 0:
        import time
        time.sleep(0.6)

    # Step 2: Force kill any remaining or background processes
    killed = 0
    for proc in psutil.process_iter(['name', 'pid']):
        try:
            p_name = proc.info['name']
            if p_name:
                p_lower = p_name.lower()
                # Protect Antigravity IDE and MCP servers
                if "antigravity" in p_lower or "codebase-memory" in p_lower:
                    continue
                if p_lower == target_exe_lower or (len(target_base) > 4 and target_base == p_lower.replace(".exe", "")):
                    proc.kill()
                    killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        except Exception:
            pass

    if graceful_closed > 0 or killed > 0:
        return f"Closed {process_name}, Sir."
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
