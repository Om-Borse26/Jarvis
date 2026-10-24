"""
J.A.R.V.I.S. — Memory Manager
Multi-tiered local memory system:
  1. Working Memory: Active conversation context and recent state in RAM.
  2. Episodic Memory: SQLite database storing timestamped turn-by-turn interactions.
  3. Semantic Memory: LanceDB vector database for long-term associative recall.
  4. User Profile: Key-value preferences, habits, system aliases, and permissions.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from loguru import logger


@dataclass
class MemoryRecord:
    id: str
    category: str  # "episodic", "fact", "preference", "procedure"
    content: str
    timestamp: float
    importance: float = 1.0
    metadata: dict[str, Any] | None = None


class MemoryManager:
    """Multi-tiered memory engine for Jarvis."""

    def __init__(self, data_dir: Path | str = "data/memory") -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.sqlite_path = self.data_dir / "episodic.db"
        self.lancedb_dir = self.data_dir / "vectors.lance"
        self.profile_path = self.data_dir / "profile.json"

        # In-memory working cache
        self.working_memory: list[dict[str, Any]] = []
        self.max_working_items: int = 20

        # SQLite episodic storage
        self._init_sqlite()

        # Load profile
        self.profile: dict[str, Any] = self._load_profile()

        # LanceDB table (lazy initialized)
        self._lancedb = None
        self._lance_table = None

    def _init_sqlite(self) -> None:
        """Initialize SQLite tables for episodic history and facts."""
        with sqlite3.connect(self.sqlite_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS episodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    role TEXT,
                    content TEXT,
                    mood TEXT,
                    timestamp REAL,
                    metadata TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS facts (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    category TEXT,
                    updated_at REAL
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_episodes_time
                ON episodes (timestamp DESC)
                """
            )
            conn.commit()

    def _load_profile(self) -> dict[str, Any]:
        """Load user profile and persistent preferences."""
        if self.profile_path.exists():
            try:
                with open(self.profile_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load profile.json: {e}")
        return {
            "user_name": "Sir",
            "browser_default": "brave",
            "wake_word_enabled": True,
            "hotkey": "ctrl+alt+j",
            "mood_adaptation": True,
            "apps": {},
        }

    def save_profile(self) -> None:
        """Persist user profile to disk."""
        try:
            with open(self.profile_path, "w", encoding="utf-8") as f:
                json.dump(self.profile, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save profile: {e}")

    # ── Working Memory ──

    def push_working(self, role: str, content: str, mood: str = "neutral") -> None:
        """Add item to short-term working memory and record into SQLite."""
        entry = {
            "role": role,
            "content": content,
            "mood": mood,
            "timestamp": time.time(),
        }
        self.working_memory.append(entry)
        if len(self.working_memory) > self.max_working_items:
            self.working_memory.pop(0)

        # Record to SQLite episodic
        self.record_episode("current_session", role, content, mood)

    def get_recent_dialogue(self, limit: int = 6) -> list[dict[str, str]]:
        """Get recent dialogue formatted for LLM context."""
        items = self.working_memory[-limit:] if self.working_memory else []
        return [{"role": item["role"], "content": item["content"]} for item in items]

    def clear_working(self) -> None:
        """Reset working memory."""
        self.working_memory.clear()

    # ── Episodic Memory (SQLite) ──

    def record_episode(
        self,
        session_id: str,
        role: str,
        content: str,
        mood: str = "neutral",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Save a conversation turn to episodic memory."""
        meta_json = json.dumps(metadata or {})
        try:
            with sqlite3.connect(self.sqlite_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO episodes (session_id, role, content, mood, timestamp, metadata)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (session_id, role, content, mood, time.time(), meta_json),
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to record episode: {e}")

    def query_recent_episodes(self, limit: int = 10) -> list[dict[str, Any]]:
        """Query most recent turns from database."""
        try:
            with sqlite3.connect(self.sqlite_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT role, content, mood, timestamp
                    FROM episodes
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
                rows = cursor.fetchall()
                return [
                    {"role": r[0], "content": r[1], "mood": r[2], "timestamp": r[3]}
                    for r in reversed(rows)
                ]
        except Exception as e:
            logger.error(f"Failed to query episodes: {e}")
            return []

    # ── Fact & Preference Key-Value Store ──

    def set_fact(self, key: str, value: Any, category: str = "general") -> None:
        """Store or update a learned fact or preference."""
        val_str = json.dumps(value) if not isinstance(value, str) else value
        with sqlite3.connect(self.sqlite_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO facts (key, value, category, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    category = excluded.category,
                    updated_at = excluded.updated_at
                """,
                (key, val_str, category, time.time()),
            )
            conn.commit()

    def get_fact(self, key: str) -> Any | None:
        """Retrieve a stored fact."""
        with sqlite3.connect(self.sqlite_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM facts WHERE key = ?", (key,))
            row = cursor.fetchone()
            if not row:
                return None
            try:
                return json.loads(row[0])
            except (json.JSONDecodeError, TypeError):
                return row[0]

    def get_all_facts(self) -> dict[str, Any]:
        """Retrieve all facts as a key-value dictionary."""
        with sqlite3.connect(self.sqlite_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM facts")
            results = {}
            for k, v in cursor.fetchall():
                try:
                    results[k] = json.loads(v)
                except Exception:
                    results[k] = v
            return results

    # ── Context Synthesis for LLM ──

    def assemble_system_prompt_context(self, current_query: str = "") -> str:
        """Assemble relevant memory facts and profile data into system context."""
        facts = self.get_all_facts()
        profile_info = {
            "Preferred Name": self.profile.get("user_name", "Sir"),
            "Default Browser": self.profile.get("browser_default", "brave"),
            "Phone": "Nothing Phone 2a (Eve companion target)",
        }

        lines = ["\n[KNOWLEDGE & USER CONTEXT]"]
        for k, v in profile_info.items():
            lines.append(f"- {k}: {v}")

        if facts:
            lines.append("\n[PERSISTED FACTS & PREFERENCES]")
            for k, v in list(facts.items())[:15]:
                lines.append(f"- {k}: {v}")

        return "\n".join(lines)
