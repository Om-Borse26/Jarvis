"""
J.A.R.V.I.S. — Procedure / Recipe Memory
Stores named multi-step routines ("my work setup" → open VS Code, open Brave,
set volume to 30) so the user can trigger a whole sequence with one phrase.

Steps are stored as plain natural-language sub-commands; replaying a procedure
runs each step back through the normal command router. Stdlib sqlite only.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import List, Optional

from loguru import logger

_WS = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    n = (name or "").lower().strip().strip("'\"")
    n = re.sub(r"\b(routine|procedure|recipe|macro)\b", "", n)
    n = re.sub(r"^(my|the|a)\s+", "", n.strip())
    return _WS.sub(" ", n).strip()


def split_steps(steps_text: str) -> List[str]:
    """Split a spoken step list into individual commands."""
    if isinstance(steps_text, list):
        raw = steps_text
    else:
        raw = re.split(r"\s*(?:;|,|\band then\b|\bthen\b|\band\b)\s*", steps_text or "")
    return [s.strip() for s in raw if s and s.strip()]


class ProcedureMemory:
    """Named routine store (singleton)."""

    _instance: Optional["ProcedureMemory"] = None

    def __new__(cls, *a, **k):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._ready = False
        return cls._instance

    def __init__(self, db_path: str | Path = "data/memory/procedures.db") -> None:
        if self._ready:
            return
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._ready = True
        logger.debug("[Memory] Procedure memory ready.")

    def _init_db(self) -> None:
        con = sqlite3.connect(self.db_path)
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS procedures (
                name  TEXT PRIMARY KEY,
                steps TEXT NOT NULL,
                ts    REAL NOT NULL
            )
            """
        )
        con.commit()
        con.close()

    def save(self, name: str, steps) -> int:
        """Store a routine. Returns the number of steps saved (0 = rejected)."""
        norm = normalize_name(name)
        step_list = split_steps(steps)
        if not norm or not step_list:
            return 0
        try:
            con = sqlite3.connect(self.db_path)
            con.execute(
                "INSERT INTO procedures (name, steps, ts) VALUES (?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET steps=excluded.steps, ts=excluded.ts",
                (norm, json.dumps(step_list), time.time()),
            )
            con.commit()
            con.close()
            return len(step_list)
        except Exception as e:
            logger.debug(f"ProcedureMemory.save notice: {e}")
            return 0

    def get(self, name: str) -> Optional[List[str]]:
        norm = normalize_name(name)
        if not norm:
            return None
        try:
            con = sqlite3.connect(self.db_path)
            row = con.execute(
                "SELECT steps FROM procedures WHERE name = ?", (norm,)
            ).fetchone()
            con.close()
            return json.loads(row[0]) if row else None
        except Exception as e:
            logger.debug(f"ProcedureMemory.get notice: {e}")
            return None

    def delete(self, name: str) -> bool:
        norm = normalize_name(name)
        try:
            con = sqlite3.connect(self.db_path)
            cur = con.execute("DELETE FROM procedures WHERE name = ?", (norm,))
            con.commit()
            deleted = cur.rowcount > 0
            con.close()
            return deleted
        except Exception:
            return False

    def all_names(self) -> List[str]:
        try:
            con = sqlite3.connect(self.db_path)
            rows = con.execute("SELECT name FROM procedures ORDER BY name").fetchall()
            con.close()
            return [r[0] for r in rows]
        except Exception:
            return []


procedure_memory = ProcedureMemory()
