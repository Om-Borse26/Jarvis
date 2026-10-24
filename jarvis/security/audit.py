"""
J.A.R.V.I.S. — Action Audit Log & Risk Classification
Append-only record of every tool execution for traceability and safety review.

- Every tool call is logged as one JSON line in data/logs/audit.jsonl.
- Argument values that look like secrets (password/token/key/etc.) are redacted
  before writing, so credentials never land in the log.
- `classify_risk()` labels actions so higher tiers (consent gate, UI) can decide
  whether to require confirmation.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from loguru import logger

_AUDIT_DIR = Path("data/logs")
_AUDIT_FILE = _AUDIT_DIR / "audit.jsonl"

# Argument keys whose values must never be written to disk.
_SENSITIVE_KEY = re.compile(r"(pass|pwd|secret|token|key|cred|auth|value)", re.IGNORECASE)

# Tools that can modify the system, spend money, message people, or destroy data.
HIGH_RISK_TOOLS = {
    "execute_shell", "execute_python",
    "delete_file", "delete_directory", "move_path", "rename_path",
    "kill_process", "shutdown_pc", "restart_pc", "sleep_pc",
    "git_push", "git_commit", "pip_install", "npm_run",
    "send_whatsapp_message", "compose_email",
    "save_secret", "delete_secret",
    "automate_browser",
}


def classify_risk(tool_name: str, args: dict[str, Any] | None = None) -> str:
    """Return 'high' for destructive/sensitive actions, otherwise 'normal'."""
    if tool_name in HIGH_RISK_TOOLS:
        return "high"
    return "normal"


def redact(args: dict[str, Any] | None) -> dict[str, Any]:
    """Return a shallow copy of args with secret-looking values masked."""
    if not args:
        return {}
    clean: dict[str, Any] = {}
    for k, v in args.items():
        if _SENSITIVE_KEY.search(str(k)):
            clean[k] = "***REDACTED***"
        elif isinstance(v, str) and len(v) > 300:
            clean[k] = v[:300] + "…"
        else:
            clean[k] = v
    return clean


def audit(
    tool_name: str,
    args: dict[str, Any] | None,
    status: str,
    result: str = "",
) -> None:
    """Append a single audit record. Never raises — logging must not break execution."""
    try:
        _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": round(time.time(), 3),
            "tool": tool_name,
            "risk": classify_risk(tool_name, args),
            "status": status,
            "args": redact(args),
            "result": (result or "")[:500],
        }
        with _AUDIT_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:  # pragma: no cover
        logger.debug(f"[Audit] Could not write audit record: {e}")
