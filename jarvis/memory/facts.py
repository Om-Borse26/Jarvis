"""
J.A.R.V.I.S. — Learned Fact Memory
A tiny self-learning store for answers Jarvis has looked up before, so a repeat
question can be answered instantly from memory instead of hitting the web again.

Deliberately simple and dependency-free (stdlib sqlite + normalized keyword
match) so it works everywhere and is easy to test. Semantic recall lives in the
L4 SemanticMemory; this is the fast, exact-ish Q→A cache that feeds it.
"""
from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path
from typing import Optional

from loguru import logger

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]")

# Common question contractions → expanded, so "what's" collapses onto "what is".
_CONTRACTIONS = {
    "what's": "what is", "whats": "what is", "who's": "who is", "whos": "who is",
    "where's": "where is", "wheres": "where is", "how's": "how is",
    "when's": "when is", "that's": "that is", "it's": "it is", "there's": "there is",
}


def _normalize(question: str) -> str:
    q = (question or "").lower().strip()
    for c, full in _CONTRACTIONS.items():
        q = re.sub(rf"\b{re.escape(c)}\b", full, q)
    q = _PUNCT.sub(" ", q)
    q = _WS.sub(" ", q).strip()
    # Drop a few leading politeness/filler tokens so phrasing variants collapse.
    q = re.sub(r"^(hey jarvis|jarvis|please|can you|could you|tell me|do you know)\s+", "", q)
    return q


class FactMemory:
    """Normalized question → answer cache (singleton)."""

    _instance: Optional["FactMemory"] = None

    def __new__(cls, *a, **k):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._ready = False
        return cls._instance

    def __init__(self, db_path: str | Path = "data/memory/facts.db") -> None:
        if self._ready:
            return
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._ready = True
        logger.debug("[Memory] Fact memory ready.")

    def _init_db(self) -> None:
        con = sqlite3.connect(self.db_path)
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS facts (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                norm_q   TEXT NOT NULL UNIQUE,
                question TEXT NOT NULL,
                answer   TEXT NOT NULL,
                source   TEXT DEFAULT 'web',
                ts       REAL NOT NULL
            )
            """
        )
        con.commit()
        con.close()

    def remember(self, question: str, answer: str, source: str = "web") -> bool:
        """Store (or refresh) a learned fact. Returns True on write."""
        norm = _normalize(question)
        if not norm or not (answer or "").strip():
            return False
        try:
            con = sqlite3.connect(self.db_path)
            con.execute(
                """
                INSERT INTO facts (norm_q, question, answer, source, ts)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(norm_q) DO UPDATE SET
                    answer=excluded.answer, source=excluded.source, ts=excluded.ts
                """,
                (norm, question.strip(), answer.strip(), source, time.time()),
            )
            con.commit()
            con.close()
            return True
        except Exception as e:
            logger.debug(f"FactMemory.remember notice: {e}")
            return False

    def recall(self, question: str) -> Optional[str]:
        """Return a stored answer for an equivalent question, or None."""
        norm = _normalize(question)
        if not norm:
            return None
        try:
            con = sqlite3.connect(self.db_path)
            row = con.execute(
                "SELECT answer FROM facts WHERE norm_q = ?", (norm,)
            ).fetchone()
            con.close()
            return row[0] if row else None
        except Exception as e:
            logger.debug(f"FactMemory.recall notice: {e}")
            return None

    def count(self) -> int:
        try:
            con = sqlite3.connect(self.db_path)
            n = con.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
            con.close()
            return int(n)
        except Exception:
            return 0


fact_memory = FactMemory()
