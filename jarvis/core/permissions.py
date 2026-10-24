"""
J.A.R.V.I.S. — Permission Policy (User-Controlled Access Gate)
A single place where YOU decide which categories of tools Jarvis may use.

Design principle: this is YOUR control surface, not Jarvis's. The policy is
changed only by you — through the dashboard or by editing config/permissions.json.
There is deliberately NO tool to grant permissions, so Jarvis can never widen its
own access. The registry hard-blocks any tool whose category is disabled.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from loguru import logger

_POLICY_PATH = Path("config/permissions.json")

# The categories you can toggle. (MCP server tools use "mcp:<server>" → base "mcp".)
KNOWN_CATEGORIES = [
    "computer_use",   # screenshot, mouse, keyboard, clicking
    "code",           # run shell / python, git, packages
    "security",       # vault, credentials, auto-fill
    "mcp",            # external MCP servers (browser, web search, …)
    "scheduler",      # reminders, recurring tasks
    "web",            # web search / open sites
    "file",           # file read/write/delete
    "process",        # launch / kill applications
    "os",             # volume, media, power, windows
    "system",         # system info, lifecycle
    "memory",         # remember / recall
    "general",        # misc / plugins
]


class PermissionPolicy:
    """User-owned allow/deny policy by tool category (singleton)."""

    def __init__(self, path: Path = _POLICY_PATH) -> None:
        self.path = path
        self._policy: Dict[str, bool] = {c: True for c in KNOWN_CATEGORIES}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                for k, v in data.items():
                    self._policy[k] = bool(v)
            except Exception as e:
                logger.warning(f"[Permissions] Could not read {self.path}: {e}")
        else:
            self.save()

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._policy, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"[Permissions] Could not save policy: {e}")

    @staticmethod
    def _base(category: str) -> str:
        return (category or "general").split(":")[0].strip().lower()

    def is_allowed(self, category: str) -> bool:
        """Default-allow unknown categories; respect explicit user toggles."""
        return self._policy.get(self._base(category), True)

    # ── User-only mutators (called by the dashboard/API, NOT by any tool) ─────
    def set(self, category: str, enabled: bool) -> None:
        self._policy[self._base(category)] = bool(enabled)
        self.save()
        logger.info(f"[Permissions] '{category}' set to {'enabled' if enabled else 'disabled'} by user.")

    def as_dict(self) -> Dict[str, bool]:
        return dict(self._policy)


# Process-wide singleton
permission_policy = PermissionPolicy()
