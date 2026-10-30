"""
J.A.R.V.I.S. — Minimal .env Loader
Loads KEY=VALUE pairs from a repo-root `.env` into the process environment so
secrets (e.g. TAVILY_API_KEY) live in ONE gitignored place. Values already set
in the real environment win — we never overwrite them.

Both consumers benefit from this single file:
  • the direct Tavily REST call (reads os.environ)
  • the Tavily MCP server subprocess (inherits os.environ via the MCP launcher)
"""
from __future__ import annotations

import os
from pathlib import Path

from loguru import logger

_ENV_PATH = Path(__file__).parent.parent.parent / ".env"
_LOADED = False


def load_env_file(path: Path = _ENV_PATH) -> None:
    """Parse a simple .env file into os.environ (idempotent, non-overriding)."""
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    try:
        if not path.exists():
            return
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
        logger.debug(f"[env] Loaded secrets from {path.name}")
    except Exception as e:
        logger.debug(f"[env] .env load notice: {e}")
