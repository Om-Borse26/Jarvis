"""
J.A.R.V.I.S. — Intent Scoping
Cheap, deterministic classifier that narrows the tool schema sent to the
local model. A weak 7B model is both slower and less accurate when handed
90+ tool definitions; scoping to the handful of relevant categories cuts the
prompt size dramatically and improves tool-selection accuracy.

Design rule (confidence fallback): only scope when we are reasonably sure.
When nothing matches, return None so the caller passes the FULL toolset —
we never trade capability for speed when the intent is ambiguous.
"""
from __future__ import annotations

from typing import Optional, List

# Category groups keyed by the tool categories declared via @register_tool.
# Each entry: group_name -> (categories, trigger_keywords)
_GROUPS: dict[str, tuple[list[str], list[str]]] = {
    "files": (
        ["filesystem"],
        ["file", "files", "folder", "directory", "folders", "rename", "move file",
         "copy file", "desktop", "document", "documents", "downloads", "save as",
         "new file", "delete file", "create folder", "make folder", "zip", "unzip"],
    ),
    "apps": (
        ["process", "window"],
        ["open", "launch", "start", "close", "kill", "quit", "terminate", "exit",
         "switch to", "focus", "bring up", "show me", "minimize", "app", "application",
         "running apps", "vscode", "vs code", "brave", "chrome", "edge", "notepad",
         "blender", "discord", "spotify", "whatsapp", "explorer"],
    ),
    "web": (
        ["web"],
        ["browser", "search", "google", "youtube", "website", "url", "tab", "navigate",
         "open a website", "go to", "reddit", "wikipedia", ".com", ".org", "web",
         "scroll", "refresh", "back", "forward", "bookmark"],
    ),
    "system": (
        ["audio", "media", "power", "system"],
        ["volume", "mute", "unmute", "louder", "quieter", "play", "pause", "resume",
         "track", "song", "music", "lock", "sleep", "shutdown", "shut down", "restart",
         "email", "gmail", "compose", "brightness", "battery"],
    ),
    "coding": (
        ["code", "shell"],
        ["run", "script", "python", "execute", "command", "terminal", "powershell",
         "code", "compile", "pip install", "npm", "git"],
    ),
    "vision": (
        ["vision", "computer_use", "gui"],
        ["screen", "screenshot", "what do you see", "look at my screen", "read my screen",
         "click", "type this", "ocr", "on my screen", "what's on"],
    ),
    "comms": (
        ["communication"],
        ["whatsapp", "message", "text", "send a message", "send message", "chat"],
    ),
    "mcp": (
        ["mcp"],
        ["mcp server", "mcp servers", "pdf", "read document", "read the document",
         "codebase", "markitdown", "docx", "xlsx", "pptx"],
    ),
    "hardware": (
        ["system", "process"],
        ["gpu", "cpu", "ram", "temperature", "hardware", "telemetry", "fan", "vram"],
    ),
}


def scope_categories(text: str) -> Optional[List[str]]:
    """
    Return the minimal set of tool categories relevant to the utterance,
    or None when the intent is ambiguous (caller should use the full toolset).
    """
    if not text:
        return None
    t = text.lower()
    matched: set[str] = set()
    for _group, (categories, keywords) in _GROUPS.items():
        if any(kw in t for kw in keywords):
            matched.update(categories)

    if not matched:
        return None

    # If the utterance lit up most of the taxonomy, it's broad/ambiguous —
    # fall back to the full toolset rather than a half-scoped guess.
    if len(matched) >= 8:
        return None

    return sorted(matched)
