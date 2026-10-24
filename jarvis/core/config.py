"""
J.A.R.V.I.S. — Configuration Loader
Reads and validates settings.toml, provides typed access throughout the app.
"""
from __future__ import annotations
import tomllib
from pathlib import Path
from functools import lru_cache
from dataclasses import dataclass, field

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "settings.toml"


@lru_cache(maxsize=1)
def load_config() -> dict:
    """Load and cache the master settings.toml."""
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


def get(section: str, key: str, default=None):
    """Safely retrieve a config value."""
    cfg = load_config()
    return cfg.get(section, {}).get(key, default)


def reload():
    """Force reload config from disk (call after user edits settings.toml)."""
    load_config.cache_clear()
    return load_config()
