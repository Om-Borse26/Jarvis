"""
J.A.R.V.I.S. — L3 Episodic Memory
A durable, timestamped log of PAST interactions: what the user asked, what Jarvis
did (which tools), and how it turned out. This is what lets Jarvis learn from
experience — "last time you asked to deploy, I ran npm build then pushed."

Backed by SQLite so it survives restarts and is cheaply searchable.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List

from loguru import logger

from jarvis.tools.registry import register_tool


class EpisodicMemory:
    """Timestamped store of past turns and their outcomes (singleton)."""

    def __init__(self, db_path: str | Path = "data/memory/episodic.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        logger.debug("[Memory] Episodic memory (L3) ready.")

    def _init_db(self) -> None:
        con = sqlite3.connect(self.db_path)
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS episodes (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ts         REAL NOT NULL,
                user_input TEXT NOT NULL,
                tools      TEXT DEFAULT '',
                outcome    TEXT DEFAULT '',
                success    INTEGER DEFAULT 1
            )
            """
        )
        con.commit()
        con.close()

    def record(
        self,
        user_input: str,
        tools_used: List[str] | None = None,
        outcome: str = "",
        success: bool = True,
    ) -> None:
        """Persist one completed interaction. Never raises."""
        if not user_input or not user_input.strip():
            return
        try:
            con = sqlite3.connect(self.db_path)
            con.execute(
                "INSERT INTO episodes (ts, user_input, tools, outcome, success) VALUES (?, ?, ?, ?, ?)",
                (
                    time.time(),
                    user_input.strip()[:500],
                    json.dumps(tools_used or []),
                    (outcome or "")[:500],
                    1 if success else 0,
                ),
            )
            con.commit()
            con.close()
        except Exception as e:
            logger.debug(f"[Memory] Episodic record failed: {e}")

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Keyword search across past interactions (most recent first)."""
        try:
            con = sqlite3.connect(self.db_path)
            if query and query.strip():
                q = f"%{query.strip()}%"
                rows = con.execute(
                    "SELECT ts, user_input, tools, outcome, success FROM episodes "
                    "WHERE user_input LIKE ? OR outcome LIKE ? ORDER BY ts DESC LIMIT ?",
                    (q, q, limit),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT ts, user_input, tools, outcome, success FROM episodes "
                    "ORDER BY ts DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            con.close()
        except Exception as e:
            logger.debug(f"[Memory] Episodic search failed: {e}")
            return []
        return [
            {
                "ts": r[0],
                "user_input": r[1],
                "tools": json.loads(r[2] or "[]"),
                "outcome": r[3],
                "success": bool(r[4]),
            }
            for r in rows
        ]

    def recent(self, limit: int = 5) -> List[Dict[str, Any]]:
        return self.search("", limit)


# Process-wide singleton
episodic_memory = EpisodicMemory()


@register_tool(
    name="recall_past_actions",
    description="Recall how a similar request was handled before (which tools Jarvis used and the outcome). Use when the user refers to a previous task or says 'do it like last time'.",
    category="memory",
)
def recall_past_actions(query: str = "") -> str:
    """Search episodic memory for past interactions matching a query."""
    episodes = episodic_memory.search(query, limit=5)
    if not episodes:
        return "I don't have a record of handling that before."
    parts = []
    for e in episodes:
        tools = ", ".join(e["tools"]) if e["tools"] else "no tools"
        status = "succeeded" if e["success"] else "failed"
        parts.append(f"You asked '{e['user_input']}' — I used {tools} and it {status}.")
    return " ".join(parts[:3])
