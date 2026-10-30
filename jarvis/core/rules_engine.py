"""
J.A.R.V.I.S. — Global Rules Engine
Enforces universal application lifecycle rules BEFORE any tool executes.

Rules:
  1.  Open if closed — launch app first if not running
  2.  Reuse existing — focus window, never spawn duplicates
  3.  Close on command — graceful WM_CLOSE, then force kill
  4.  Tab reuse — navigate in active browser tab
  5.  Workspace awareness — know active VS Code project, browser tabs
  6.  Confirm destructive — ask before delete/shutdown
  7.  Recycle bin — move to trash instead of permanent delete
  8.  Rate limiting — don't spam-click UI elements
  9.  Fallback chain — native → computer use → playwright → code gen → ask user
  10. Error recovery — retry → alternative → report
  11. Context persistence — "do the same thing" = repeat last action
  12. Implicit context — "delete it" = delete the thing just mentioned
  13. Batch operations — "create 5 files" = loop 5 times
  14. Progress reporting — speak progress for multi-step tasks
  15. Permission escalation — explain and ask for admin ops
  16. Time awareness — "in 10 minutes" = set timer
  17. App shortcuts — know Ctrl+S, Ctrl+Z, Ctrl+Shift+P, etc.
  18. Natural language paths — "my downloads" = ~/Downloads
  19. Safe mode — explain risky shell commands before executing
  20. Graceful degradation — fallback if GPU busy or Ollama slow
"""
from __future__ import annotations

import os
import time
import asyncio
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any, Callable
from loguru import logger


# ─── Process Name Resolution ───────────────────────────────────────────────────
# Maps common spoken app names → actual Windows process names (.exe)
PROCESS_NAME_MAP: Dict[str, str] = {
    # Editors & IDEs
    "vscode": "Code.exe",
    "vs code": "Code.exe",
    "visual studio code": "Code.exe",
    "code": "Code.exe",

    # Browsers
    "brave": "brave.exe",
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "edge": "msedge.exe",
    "microsoft edge": "msedge.exe",
    "firefox": "firefox.exe",
    "opera": "opera.exe",

    # Communication
    "discord": "Discord.exe",
    "whatsapp": "WhatsApp.exe",
    "telegram": "Telegram.exe",
    "teams": "ms-teams.exe",
    "microsoft teams": "ms-teams.exe",
    "slack": "slack.exe",
    "zoom": "Zoom.exe",

    # Media & Creative
    "spotify": "Spotify.exe",
    "blender": "blender.exe",
    "photoshop": "Photoshop.exe",
    "premiere": "Adobe Premiere Pro.exe",
    "after effects": "AfterFX.exe",
    "obs": "obs64.exe",
    "obs studio": "obs64.exe",
    "vlc": "vlc.exe",

    # Development
    "terminal": "WindowsTerminal.exe",
    "windows terminal": "WindowsTerminal.exe",
    "powershell": "powershell.exe",
    "cmd": "cmd.exe",
    "command prompt": "cmd.exe",
    "git bash": "git-bash.exe",
    "postman": "Postman.exe",
    "docker": "Docker Desktop.exe",

    # System
    "notepad": "notepad.exe",
    "calculator": "Calculator.exe",
    "calc": "Calculator.exe",
    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",
    "task manager": "Taskmgr.exe",
    "settings": "SystemSettings.exe",

    # Games & Other
    "steam": "steam.exe",
    "epic": "EpicGamesLauncher.exe",
    "epic games": "EpicGamesLauncher.exe",
}


# ─── Natural Language Path Resolution ──────────────────────────────────────────
def resolve_natural_path(text: str) -> Optional[str]:
    """
    Convert natural language folder references to actual filesystem paths.
    e.g. "my downloads" → C:\\Users\\ombor\\Downloads
    """
    user_home = Path.home()
    text_lower = text.lower().strip()

    NL_PATH_MAP = {
        "desktop": str(user_home / "Desktop"),
        "my desktop": str(user_home / "Desktop"),
        "downloads": str(user_home / "Downloads"),
        "my downloads": str(user_home / "Downloads"),
        "download folder": str(user_home / "Downloads"),
        "documents": str(user_home / "Documents"),
        "my documents": str(user_home / "Documents"),
        "pictures": str(user_home / "Pictures"),
        "my pictures": str(user_home / "Pictures"),
        "music": str(user_home / "Music"),
        "my music": str(user_home / "Music"),
        "videos": str(user_home / "Videos"),
        "my videos": str(user_home / "Videos"),
        "home": str(user_home),
        "home folder": str(user_home),
        "my home": str(user_home),
        "projects": str(Path("D:/02_Interests (Up Skilling )/04_Projects")),
        "my projects": str(Path("D:/02_Interests (Up Skilling )/04_Projects")),
        "project folder": str(Path("D:/02_Interests (Up Skilling )/04_Projects")),
        "temp": str(Path(os.environ.get("TEMP", "C:/Temp"))),
        "temporary": str(Path(os.environ.get("TEMP", "C:/Temp"))),
        "appdata": str(Path(os.environ.get("APPDATA", ""))),
        "root": "C:\\",
        "c drive": "C:\\",
        "d drive": "D:\\",
    }

    for phrase, path in NL_PATH_MAP.items():
        if phrase in text_lower:
            return path
    return None


# ─── App Keyboard Shortcuts ───────────────────────────────────────────────────
APP_SHORTCUTS: Dict[str, Dict[str, List[str]]] = {
    "vscode": {
        "save": ["ctrl", "s"],
        "save all": ["ctrl", "k", "s"],
        "undo": ["ctrl", "z"],
        "redo": ["ctrl", "shift", "z"],
        "command palette": ["ctrl", "shift", "p"],
        "terminal": ["ctrl", "`"],
        "new file": ["ctrl", "n"],
        "close file": ["ctrl", "w"],
        "close window": ["alt", "f4"],
        "find": ["ctrl", "f"],
        "replace": ["ctrl", "h"],
        "go to file": ["ctrl", "p"],
        "toggle sidebar": ["ctrl", "b"],
        "format document": ["shift", "alt", "f"],
        "open settings": ["ctrl", ","],
    },
    "browser": {
        "new tab": ["ctrl", "t"],
        "close tab": ["ctrl", "w"],
        "reopen tab": ["ctrl", "shift", "t"],
        "next tab": ["ctrl", "tab"],
        "previous tab": ["ctrl", "shift", "tab"],
        "address bar": ["ctrl", "l"],
        "refresh": ["f5"],
        "hard refresh": ["ctrl", "shift", "r"],
        "back": ["alt", "left"],
        "forward": ["alt", "right"],
        "find": ["ctrl", "f"],
        "bookmark": ["ctrl", "d"],
        "dev tools": ["f12"],
        "full screen": ["f11"],
        "downloads": ["ctrl", "j"],
        "history": ["ctrl", "h"],
    },
    "general": {
        "copy": ["ctrl", "c"],
        "paste": ["ctrl", "v"],
        "cut": ["ctrl", "x"],
        "undo": ["ctrl", "z"],
        "redo": ["ctrl", "y"],
        "select all": ["ctrl", "a"],
        "save": ["ctrl", "s"],
        "close": ["alt", "f4"],
        "minimize": ["win", "down"],
        "maximize": ["win", "up"],
        "switch app": ["alt", "tab"],
        "task manager": ["ctrl", "shift", "escape"],
        "lock": ["win", "l"],
        "screenshot": ["win", "shift", "s"],
        "emoji": ["win", "."],
    },
}


# ─── Implicit Context Tracker ─────────────────────────────────────────────────
@dataclass
class ActionContext:
    """Tracks the last action for implicit references like 'delete it', 'open it', 'do it again'."""
    last_tool: str = ""
    last_args: Dict[str, Any] = field(default_factory=dict)
    last_result: str = ""
    last_entity: str = ""          # "demo_folder", "index.html", "brave", etc.
    last_entity_type: str = ""     # "file", "folder", "app", "url", "tab"
    last_path: str = ""            # Full path if filesystem entity
    last_app: str = ""             # Last app interacted with
    timestamp: float = 0.0


class RulesEngine:
    """
    Global rules enforcement layer that wraps tool execution.
    Ensures consistent, predictable behavior across ALL interactions.
    """

    def __init__(self):
        self.context = ActionContext()
        self._rate_limit_last: Dict[str, float] = {}
        self._rate_limit_min_interval = 0.3  # seconds between repeated UI actions

    def resolve_process_name(self, app_name: str) -> str:
        """Map spoken app name to actual Windows process name."""
        clean = app_name.lower().strip().rstrip(".exe")
        if clean in PROCESS_NAME_MAP:
            return PROCESS_NAME_MAP[clean]
        # Fuzzy match: check if any key contains the query or vice versa
        for key, exe in PROCESS_NAME_MAP.items():
            if clean in key or key in clean:
                return exe
        # Fallback: assume it's the process name itself
        return f"{clean}.exe" if not clean.endswith(".exe") else clean

    # ── Centralized behavioral policies ──────────────────────────────────
    # Single source of truth for the "reuse vs. new" and "resolve" decisions
    # that tool modules used to each re-implement inline.
    _NEW_INSTANCE_WORDS = ("new window", "another instance", "another window",
                           "separate window", "duplicate", "fresh", "new tab")

    def should_reuse_window(self, app_name: str, force_new: bool = False) -> bool:
        """Single-instance policy: reuse an existing window unless the user
        explicitly asked for a new/duplicate one."""
        if force_new:
            return False
        q = (app_name or "").lower()
        return not any(w in q for w in self._NEW_INSTANCE_WORDS)

    def should_reuse_tab(self, request_text: str = "", force_new: bool = False,
                         new_tab: bool = False) -> bool:
        """Tab-reuse policy: navigate in the active tab unless a new tab/window
        was explicitly requested."""
        if force_new or new_tab:
            return False
        q = (request_text or "").lower()
        return not any(w in q for w in ("new tab", "another tab", "new window"))

    def resolve_path(self, text: str) -> Optional[str]:
        """Natural-language path resolution (e.g. 'my downloads' → ~/Downloads)."""
        return resolve_natural_path(text)

    def requires_confirmation(self, tool_name: str, args: Dict[str, Any]) -> bool:
        """Unified gate: a tool needs spoken confirmation if it is destructive."""
        return self.is_destructive(tool_name, args or {})

    def update_context(
        self,
        tool: str,
        args: Dict[str, Any],
        result: str,
        entity: str = "",
        entity_type: str = "",
        path: str = "",
        app: str = "",
    ):
        """Record the last action for implicit reference resolution."""
        self.context = ActionContext(
            last_tool=tool,
            last_args=args,
            last_result=result,
            last_entity=entity or self.context.last_entity,
            last_entity_type=entity_type or self.context.last_entity_type,
            last_path=path or self.context.last_path,
            last_app=app or self.context.last_app,
            timestamp=time.time(),
        )

    def resolve_implicit(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Resolve implicit references like 'it', 'that', 'the same thing'.
        Returns (tool_name, args) if an implicit reference is found.
        """
        lower = text.lower().strip()
        if not self.context.last_tool:
            return None

        # "do it again", "repeat", "do the same thing"
        if any(phrase in lower for phrase in ["do it again", "repeat", "same thing", "again", "do that again"]):
            return {"tool": self.context.last_tool, "args": self.context.last_args}

        # "delete it", "remove it", "open it"
        if "it" in lower.split() or "that" in lower.split():
            if self.context.last_entity:
                return {
                    "entity": self.context.last_entity,
                    "entity_type": self.context.last_entity_type,
                    "path": self.context.last_path,
                }
        return None

    def check_rate_limit(self, action_key: str) -> bool:
        """Prevent rapid-fire UI actions that could cause issues."""
        now = time.time()
        last = self._rate_limit_last.get(action_key, 0.0)
        if now - last < self._rate_limit_min_interval:
            logger.debug(f"Rate-limited action: {action_key}")
            return False
        self._rate_limit_last[action_key] = now
        return True

    def is_destructive(self, tool_name: str, args: Dict[str, Any]) -> bool:
        """Check if an action is destructive and should require confirmation."""
        DESTRUCTIVE_TOOLS = {
            "delete_file", "delete_directory", "kill_process",
            "shutdown_pc", "restart_pc", "execute_shell",
        }
        if tool_name in DESTRUCTIVE_TOOLS:
            return True
        # Shell commands that modify system state
        if tool_name == "execute_shell":
            cmd = args.get("command", "").lower()
            danger_words = ["rm ", "rmdir", "del ", "format", "reg delete", "shutdown", "restart"]
            return any(d in cmd for d in danger_words)
        return False

    # Tools that pull a (usually different) window to the foreground and thus
    # interrupt whatever the user is doing. Explicit user-initiated focus
    # (focus_application) is intentionally NOT here — the user asked for it.
    FOCUS_STEALING_TOOLS = {
        "focus_window", "keyboard_type", "keyboard_hotkey", "keyboard_press",
        "mouse_click", "mouse_move", "click_text", "type_text",
    }

    def steals_focus(self, tool_name: str, args: Optional[Dict[str, Any]] = None) -> bool:
        """True if running this tool will likely take foreground focus from the user."""
        if tool_name == "launch_application":
            return bool((args or {}).get("force_new"))
        return tool_name in self.FOCUS_STEALING_TOOLS

    def get_app_shortcut(self, app: str, action: str) -> Optional[List[str]]:
        """Get keyboard shortcut for a specific action in a specific app."""
        app_lower = app.lower().strip()
        action_lower = action.lower().strip()

        # Determine app category
        if any(a in app_lower for a in ["vscode", "vs code", "code", "visual studio"]):
            app_key = "vscode"
        elif any(a in app_lower for a in ["brave", "chrome", "edge", "firefox", "browser"]):
            app_key = "browser"
        else:
            app_key = "general"

        shortcuts = APP_SHORTCUTS.get(app_key, APP_SHORTCUTS["general"])
        return shortcuts.get(action_lower)


# Global singleton
rules_engine = RulesEngine()
