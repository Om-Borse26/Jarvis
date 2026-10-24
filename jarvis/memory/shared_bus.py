"""
J.A.R.V.I.S. — Shared Memory Bus (Jarvis ↔ Eve)
A small SQLite store both agents read/write so they stay in sync across devices:

  - events: a durable queue of hand-offs and notifications addressed to a target
    ("eve" or "jarvis"). Example: a reminder that fired while the PC was off is
    queued for "eve" to deliver on the phone; a task Eve captured on the phone is
    queued for "jarvis" to surface when you're back at the desk.
  - kv: shared profile/preferences both agents can read.

Eve (the phone companion) is a future client; this bus is the contract it will
sync against. The DB can live on a synced folder or be replicated later.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from jarvis.tools.registry import register_tool


class SharedBus:
    """Cross-agent event queue + shared key/value store (singleton)."""

    def __init__(self, db_path: str | Path = "data/memory/shared.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        logger.debug("[SharedBus] Ready.")

    def _init_db(self) -> None:
        con = sqlite3.connect(self.db_path)
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                ts      REAL NOT NULL,
                type    TEXT NOT NULL,
                payload TEXT NOT NULL,
                target  TEXT NOT NULL,
                status  TEXT NOT NULL DEFAULT 'pending'
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS kv (
                key     TEXT PRIMARY KEY,
                value   TEXT NOT NULL,
                updated REAL NOT NULL
            )
            """
        )
        con.commit()
        con.close()

    # ── Event queue ───────────────────────────────────────────────────────────
    def push_event(self, type_: str, payload: Dict[str, Any], target: str = "eve") -> int:
        con = sqlite3.connect(self.db_path)
        cur = con.execute(
            "INSERT INTO events (ts, type, payload, target, status) VALUES (?, ?, ?, ?, 'pending')",
            (time.time(), type_, json.dumps(payload or {}), target),
        )
        con.commit()
        eid = cur.lastrowid
        con.close()
        logger.info(f"[SharedBus] Queued '{type_}' for {target} (#{eid}).")
        return eid

    def pending(self, target: str, limit: int = 20) -> List[Dict[str, Any]]:
        con = sqlite3.connect(self.db_path)
        rows = con.execute(
            "SELECT id, ts, type, payload FROM events WHERE target = ? AND status = 'pending' ORDER BY ts LIMIT ?",
            (target, limit),
        ).fetchall()
        con.close()
        out = []
        for r in rows:
            try:
                payload = json.loads(r[3])
            except Exception:
                payload = {}
            out.append({"id": r[0], "ts": r[1], "type": r[2], "payload": payload})
        return out

    def ack(self, event_id: int) -> None:
        con = sqlite3.connect(self.db_path)
        con.execute("UPDATE events SET status = 'done' WHERE id = ?", (event_id,))
        con.commit()
        con.close()

    # ── Shared key/value ──────────────────────────────────────────────────────
    def set_kv(self, key: str, value: str) -> None:
        con = sqlite3.connect(self.db_path)
        con.execute(
            "INSERT INTO kv (key, value, updated) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated = excluded.updated",
            (key, value, time.time()),
        )
        con.commit()
        con.close()

    def get_kv(self, key: str, default: Optional[str] = None) -> Optional[str]:
        con = sqlite3.connect(self.db_path)
        row = con.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        con.close()
        return row[0] if row else default


# Process-wide singleton
shared_bus = SharedBus()


@register_tool(
    name="note_for_eve",
    description="Queue a note or task for Eve (the phone companion) to deliver or handle when you're on your phone.",
    category="memory",
)
def note_for_eve(text: str) -> str:
    """Hand a note/task off to Eve via the shared bus."""
    shared_bus.push_event("note", {"text": text}, target="eve")
    return "I've passed that along to Eve for your phone."


@register_tool(
    name="check_eve_updates",
    description="Check for notes or tasks Eve queued from the phone while you were away.",
    category="memory",
)
def check_eve_updates() -> str:
    """Read and acknowledge pending items Eve queued for Jarvis."""
    items = shared_bus.pending(target="jarvis", limit=10)
    if not items:
        return "Nothing new from Eve."
    texts = [i["payload"].get("text", "") for i in items if i["payload"].get("text")]
    for i in items:
        shared_bus.ack(i["id"])
    return "From Eve: " + "; ".join(texts) + "." if texts else "Nothing new from Eve."
