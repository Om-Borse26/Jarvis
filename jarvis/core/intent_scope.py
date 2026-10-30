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

import re
from typing import Optional, List, Tuple

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
         "email", "gmail", "compose", "brightness", "brighten", "dim", "sound", "audio", "battery", "master volume"],
    ),
    "scheduler": (
        ["scheduler"],
        ["remind", "reminder", "reminders", "alarm", "schedule", "meeting", "timer",
         "recurring", "calendar", "appointment", "stand up", "stretch", "drink water"],
    ),
    "memory": (
        ["memory"],
        ["remember", "favorite", "favourite", "preference", "preferences", "recall",
         "memory", "memories", "who am i", "my name"],
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
         "codebase", "markitdown", "docx", "xlsx", "pptx", "playwright",
         "automate the browser", "browser automation", "scrape", "fill the form", "fill out the form"],
    ),
    "hardware": (
        ["system", "process"],
        ["gpu", "cpu", "ram", "temperature", "hardware", "telemetry", "fan", "vram"],
    ),
}


def _kw_pattern(keywords: List[str]) -> "re.Pattern[str]":
    # Whole-word match (plural allowed) so "play" doesn't fire inside "playwright".
    def alt(ks):
        return "|".join(re.escape(k) for k in sorted(ks, key=len, reverse=True))
    words = [k for k in keywords if k[:1].isalnum()]
    suffixes = [k for k in keywords if not k[:1].isalnum()]  # e.g. ".com"
    parts = []
    if words:
        parts.append(rf"(?<!\w)(?:{alt(words)})(?:s|es)?(?!\w)")
    if suffixes:
        parts.append(rf"(?:{alt(suffixes)})(?!\w)")
    return re.compile("|".join(parts))


_GROUP_PATTERNS = [(cats, _kw_pattern(kws)) for cats, kws in _GROUPS.values()]


def scope_categories(text: str) -> Optional[List[str]]:
    """
    Return the minimal set of tool categories relevant to the utterance,
    or None when the intent is ambiguous (caller should use the full toolset).
    """
    if not text:
        return None
    t = text.lower()
    matched: set[str] = set()
    for categories, pattern in _GROUP_PATTERNS:
        if pattern.search(t):
            matched.update(categories)

    if not matched:
        return None

    # If the utterance lit up most of the taxonomy, it's broad/ambiguous —
    # fall back to the full toolset rather than a half-scoped guess.
    if len(matched) >= 8:
        return None

    return sorted(matched)


_SMALLTALK = re.compile(
    r"^(?:hey |hi |ok |okay )?(?:jarvis[, ]*)?"
    r"(?:hi|hello|hey|yo|good (?:morning|afternoon|evening|night)|"
    r"how are you(?: doing)?(?: today)?|how(?:'s| is) it going|how have you been|what'?s up|sup|"
    r"how was your day|are you there|can you hear me|you there|"
    r"thanks?(?: you)?(?: so much| a lot)?|thank you(?: very much)?|cheers|"
    r"who are you|what are you|what(?:'s| is) your name|"
    r"tell me a joke|say something funny|make me laugh|"
    r"i(?:'m| am) (?:tired|bored|happy|sad|good|fine|great|okay|ok|back|home|stressed)|"
    r"you(?:'re| are) (?:awesome|great|amazing|funny|the best|smart|cool)|"
    r"nice|cool|great|awesome|perfect|ok|okay|alright|got it|never ?mind|"
    r"bye|goodbye|see you(?: later)?|good ?night)"
    r"(?:[, ]+(?:jarvis|sir|buddy|mate))?$"
)

_QUESTION_START = re.compile(
    r"^(?:what|whats|what's|why|how|who|when|where|which|is|are|do|does|can|could|"
    r"would|should|explain|describe|tell me)\b"
)


def _clean(text: str) -> str:
    t = (text or "").lower().strip()
    t = re.sub(r"[^\w\s']", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def is_smalltalk(text: str) -> bool:
    """Greetings, thanks, 'how are you', etc. — never needs a tool."""
    return bool(_SMALLTALK.match(_clean(text)))


def select_tools(text: str) -> Tuple[List[dict], Optional[List[str]]]:
    """
    Decide which tool schemas to offer the model for this utterance.

    Returns (tools, scoped_categories):
      • small talk                    → no tools (just talk)
      • a question with no tool scope → no tools (answer it, don't act)
      • scoped request                → only those categories
      • unscoped command              → built-in tools only (no external MCP)
    """
    from jarvis.tools.registry import registry

    if is_smalltalk(text):
        return [], None
    scoped = scope_categories(text)
    if scoped is None and _QUESTION_START.match(_clean(text)):
        return [], None
    return registry.get_tools_schema(scoped), scoped
