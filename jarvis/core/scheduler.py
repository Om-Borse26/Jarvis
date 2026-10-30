"""
J.A.R.V.I.S. — Proactivity & Scheduler Engine
Lets Jarvis act on its own schedule: one-shot reminders ("remind me in 10
minutes"), timed tasks ("at 3pm"), and recurring routines ("every morning").

- Jobs persist in SQLite so they survive restarts.
- A lightweight async loop fires due jobs: it either speaks a reminder or runs a
  command through the agent (for "do" tasks like "every morning open my email").
- Natural-language times are parsed by `parse_when` (no heavy date library).
"""
from __future__ import annotations

import datetime
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from jarvis.tools.registry import register_tool


# ─── Natural-language time parsing ────────────────────────────────────────────

_UNIT_SECONDS = {"second": 1, "sec": 1, "minute": 60, "min": 60, "hour": 3600, "day": 86400}
_TIME_OF_DAY = {"morning": 8, "afternoon": 14, "evening": 18, "night": 21, "noon": 12, "midnight": 0}


def _next_daily(hour: int, minute: int = 0) -> float:
    now = datetime.datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    return target.timestamp()


def _parse_clock(text: str) -> Optional[tuple[int, int]]:
    """Parse 'at 3pm', '15:30', '9:00 am' → (hour, minute)."""
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    ampm = m.group(3)
    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return hour, minute
    return None


def parse_when(when: str) -> Optional[Dict[str, Any]]:
    """
    Parse a schedule phrase into {kind, fire_at, interval}.
      kind: 'once' | 'recurring'
      fire_at: epoch seconds of the first firing
      interval: seconds between firings (recurring only)
    Returns None if unparseable.
    """
    if not when:
        return None
    t = when.strip().lower()
    t = re.sub(r"\b(?:a|an|one)\s+(second|minute|hour|day)\b", r"1 \1", t)
    now = time.time()

    # Recurring: "every N minutes/hours", "every hour", "every day/morning/..."
    if t.startswith("every") or "each" in t:
        m = re.search(r"every\s+(\d+)\s*(second|sec|minute|min|hour|day)s?", t)
        if m:
            interval = int(m.group(1)) * _UNIT_SECONDS[m.group(2)]
            if interval <= 0:
                return None
            return {"kind": "recurring", "fire_at": now + interval, "interval": interval}
        for word, hour in _TIME_OF_DAY.items():
            if word in t:
                clock = _parse_clock(t) or (hour, 0)
                return {"kind": "recurring", "fire_at": _next_daily(*clock), "interval": 86400}
        if "hour" in t:
            return {"kind": "recurring", "fire_at": now + 3600, "interval": 3600}
        if "day" in t:
            clock = _parse_clock(t) or (9, 0)
            return {"kind": "recurring", "fire_at": _next_daily(*clock), "interval": 86400}

    # One-shot relative: "in 10 minutes", "in 2 hours", "in 30 seconds"
    m = re.search(r"in\s+(\d+)\s*(second|sec|minute|min|hour|day)s?", t)
    if m:
        delta = int(m.group(1)) * _UNIT_SECONDS[m.group(2)]
        if delta <= 0:
            return None
        return {"kind": "once", "fire_at": now + delta, "interval": None}

    # One-shot absolute: "tomorrow at 9am", "at 3pm", "15:30"
    clock = _parse_clock(t)
    if clock:
        fire_at = _next_daily(*clock)
        if "tomorrow" in t:
            fire_at = _next_daily(*clock)
            if fire_at - now < 43200:  # ensure it's genuinely tomorrow
                fire_at += 86400
        for word, hour in _TIME_OF_DAY.items():
            if word in t and ":" not in t:
                fire_at = _next_daily(hour, 0)
        return {"kind": "once", "fire_at": fire_at, "interval": None}

    # Bare time-of-day word: "remind me every evening" handled above; "at night"
    for word, hour in _TIME_OF_DAY.items():
        if word in t:
            return {"kind": "once", "fire_at": _next_daily(hour, 0), "interval": None}

    return None


# ─── Scheduler ────────────────────────────────────────────────────────────────

class Scheduler:
    """Persistent job scheduler with an async firing loop (singleton)."""

    TICK_SECONDS = 15

    def __init__(self, db_path: str | Path = "data/memory/schedule.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self.speak_fn: Optional[Callable] = None     # async: announce reminders
        self.command_fn: Optional[Callable] = None   # async: run a "do" task through the agent
        self.notify_fn: Optional[Callable] = None    # sync: push a visual HUD notification
        self._task = None
        logger.debug("[Scheduler] Ready.")

    def _init_db(self) -> None:
        con = sqlite3.connect(self.db_path)
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                kind     TEXT NOT NULL,
                action   TEXT NOT NULL DEFAULT 'speak',
                text     TEXT NOT NULL,
                fire_at  REAL NOT NULL,
                interval REAL,
                active   INTEGER DEFAULT 1,
                created  REAL NOT NULL
            )
            """
        )
        # Migrate older DBs: importance + event time (for meetings) columns.
        for col, ddl in (("importance", "TEXT DEFAULT 'normal'"), ("event_at", "REAL")):
            try:
                con.execute(f"ALTER TABLE jobs ADD COLUMN {col} {ddl}")
            except Exception:
                pass
        con.commit()
        con.close()

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    def start(self) -> None:
        import asyncio
        self.reconcile_missed()
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._tick_loop(), name="scheduler")
            logger.info("[Scheduler] Firing loop started.")

    def reconcile_missed(self) -> None:
        """
        At startup, decide what to do with jobs that came due while Jarvis was off:
          - recurring: fast-forward to the next future slot (don't replay old ones)
          - once + important/critical and still relevant: let it surface now
          - everything else: skip it and hand it off to Eve for the phone
        """
        now = time.time()
        try:
            con = sqlite3.connect(self.db_path)
            rows = con.execute(
                "SELECT id, kind, text, fire_at, interval, importance, event_at "
                "FROM jobs WHERE active = 1 AND fire_at <= ?",
                (now,),
            ).fetchall()
            con.close()
        except Exception as e:
            logger.debug(f"[Scheduler] reconcile read failed: {e}")
            return

        for jid, kind, text, fire_at, interval, importance, event_at in rows:
            if kind == "recurring" and interval:
                nxt = fire_at
                while nxt <= now:
                    nxt += interval
                self._reschedule(jid, nxt)
                continue
            if self._is_relevant(importance or "normal", fire_at, event_at, now):
                continue  # leave active → fires on the first tick
            self._deactivate(jid)
            self._handoff_to_eve(text, importance or "normal", fire_at, event_at)

    @staticmethod
    def _is_relevant(importance: str, fire_at: float, event_at: Optional[float], now: float) -> bool:
        """Should a missed one-shot job still surface on startup?"""
        if event_at:  # a meeting — only matters if the meeting hasn't happened yet
            return event_at > now
        if importance == "critical":
            return (now - fire_at) < 24 * 3600
        if importance == "important":
            return (now - fire_at) < 2 * 3600
        return False  # normal reminders never replay after a miss

    def _handoff_to_eve(self, text: str, importance: str, fire_at: float, event_at: Optional[float]) -> None:
        try:
            from jarvis.memory.shared_bus import shared_bus
            shared_bus.push_event(
                "missed_reminder",
                {"text": text, "importance": importance, "due": fire_at, "event_at": event_at},
                target="eve",
            )
        except Exception as e:
            logger.debug(f"[Scheduler] Eve handoff failed: {e}")

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()

    async def _tick_loop(self) -> None:
        import asyncio
        try:
            while True:
                await asyncio.sleep(self.TICK_SECONDS)
                try:
                    await self._fire_due()
                except Exception as e:
                    logger.debug(f"[Scheduler] tick error: {e}")
        except asyncio.CancelledError:
            pass

    async def _fire_due(self) -> None:
        now = time.time()
        con = sqlite3.connect(self.db_path)
        rows = con.execute(
            "SELECT id, kind, action, text, fire_at, interval FROM jobs WHERE active = 1 AND fire_at <= ?",
            (now,),
        ).fetchall()
        con.close()
        for jid, kind, action, text, _fire_at, interval in rows:
            await self._fire_one(jid, action, text)
            if kind == "recurring" and interval:
                self._reschedule(jid, now + interval)
            else:
                self._deactivate(jid)

    async def _fire_one(self, jid: int, action: str, text: str) -> None:
        logger.info(f"[Scheduler] Firing job {jid} ({action}): {text}")
        try:
            if self.notify_fn:
                self.notify_fn("Reminder", text)
            if action == "command" and self.command_fn:
                await self.command_fn(text)
            elif self.speak_fn:
                await self.speak_fn(f"Reminder: {text}")
        except Exception as e:
            logger.warning(f"[Scheduler] Job {jid} failed: {e}")

    def _reschedule(self, jid: int, next_at: float) -> None:
        con = sqlite3.connect(self.db_path)
        con.execute("UPDATE jobs SET fire_at = ? WHERE id = ?", (next_at, jid))
        con.commit()
        con.close()

    def _deactivate(self, jid: int) -> None:
        con = sqlite3.connect(self.db_path)
        con.execute("UPDATE jobs SET active = 0 WHERE id = ?", (jid,))
        con.commit()
        con.close()

    # ── CRUD ──────────────────────────────────────────────────────────────────
    def add_job(
        self, kind: str, text: str, fire_at: float, interval: Optional[float],
        action: str = "speak", importance: str = "normal", event_at: Optional[float] = None,
    ) -> int:
        con = sqlite3.connect(self.db_path)
        cur = con.execute(
            "INSERT INTO jobs (kind, action, text, fire_at, interval, active, created, importance, event_at) "
            "VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)",
            (kind, action, text, fire_at, interval, time.time(), importance, event_at),
        )
        con.commit()
        jid = cur.lastrowid
        con.close()
        return jid or 0

    def list_jobs(self) -> List[Dict[str, Any]]:
        con = sqlite3.connect(self.db_path)
        rows = con.execute(
            "SELECT id, kind, action, text, fire_at, interval, importance FROM jobs WHERE active = 1 ORDER BY fire_at"
        ).fetchall()
        con.close()
        return [
            {"id": r[0], "kind": r[1], "action": r[2], "text": r[3],
             "fire_at": r[4], "interval": r[5], "importance": r[6]}
            for r in rows
        ]

    def cancel(self, jid: int) -> bool:
        con = sqlite3.connect(self.db_path)
        cur = con.execute("UPDATE jobs SET active = 0 WHERE id = ? AND active = 1", (jid,))
        con.commit()
        changed = cur.rowcount > 0
        con.close()
        return changed


# Process-wide singleton
scheduler = Scheduler()


def _fmt_eta(fire_at: float) -> str:
    secs = max(0, int(fire_at - time.time()))
    if secs < 90:
        return f"in {secs} seconds"
    mins = secs // 60
    if mins < 90:
        return f"in {mins} minutes"
    hours = mins / 60
    if hours < 48:
        when = datetime.datetime.fromtimestamp(fire_at).strftime("%H:%M")
        return f"at {when}"
    return datetime.datetime.fromtimestamp(fire_at).strftime("%a %H:%M")


# ─── Agent-exposed tools ──────────────────────────────────────────────────────

@register_tool(
    name="set_reminder",
    description="Set a one-time reminder. `when` accepts 'in 10 minutes', 'in 2 hours', 'at 3pm', 'tomorrow at 9am'. `importance` can be 'normal', 'important', or 'critical' — only important/critical reminders resurface if they were missed while the PC was off (normal ones are handed to Eve instead).",
    category="scheduler",
)
def set_reminder(text: str = "", when: str = "in 5 minutes", importance: str = "normal", reminder: str = "", *args, **kwargs) -> str:
    """Schedule a one-shot spoken reminder."""
    clean_text = text or reminder or kwargs.get("message") or kwargs.get("task") or "Reminder"
    clean_when = when or kwargs.get("time") or "in 5 minutes"
    parsed = parse_when(clean_when)
    if not parsed:
        return f"I couldn't understand the time '{clean_when}'. Try 'in 10 minutes' or 'at 3pm'."
    imp = importance.lower() if str(importance).lower() in ("normal", "important", "critical") else "normal"
    jid = scheduler.add_job("once", clean_text, parsed["fire_at"], None, action="speak", importance=imp)
    return f"Reminder set ({jid}). I'll remind you {_fmt_eta(parsed['fire_at'])}."


@register_tool(
    name="schedule_meeting",
    description="Schedule a meeting reminder. `when` is the meeting time ('at 3pm', 'tomorrow at 10am'). Jarvis reminds you `lead_minutes` before (default 15). If the PC is off at that time, it's handed to Eve for your phone.",
    category="scheduler",
)
def schedule_meeting(title: str, when: str, lead_minutes: int = 15) -> str:
    """Schedule a meeting with a lead-time reminder."""
    parsed = parse_when(when)
    if not parsed:
        return f"I couldn't understand the meeting time '{when}'. Try 'at 3pm' or 'tomorrow at 10am'."
    event_at = parsed["fire_at"]
    lead = max(1, lead_minutes) * 60
    fire_at = event_at - lead
    if fire_at <= time.time():
        fire_at = time.time() + 30  # meeting is imminent — remind right away
    jid = scheduler.add_job(
        "once", f"Meeting: {title}", fire_at, None,
        action="speak", importance="important", event_at=event_at,
    )
    event_str = datetime.datetime.fromtimestamp(event_at).strftime("%H:%M")
    return f"Meeting '{title}' scheduled ({jid}). I'll remind you {lead_minutes} minutes before, around {_fmt_eta(fire_at)} (meeting at {event_str})."


@register_tool(
    name="set_recurring_task",
    description="Set a recurring routine. `when` accepts 'every morning', 'every day at 8am', 'every hour', 'every 30 minutes'. action='speak' to remind, or action='do' to actually carry out the task through Jarvis.",
    category="scheduler",
)
def set_recurring_task(text: str, when: str, action: str = "speak") -> str:
    """Schedule a recurring reminder or action."""
    parsed = parse_when(when)
    if not parsed or parsed["kind"] != "recurring":
        return f"I couldn't understand the recurring schedule '{when}'. Try 'every morning' or 'every 2 hours'."
    act = "command" if action.lower() in ("do", "command", "execute") else "speak"
    jid = scheduler.add_job("recurring", text, parsed["fire_at"], parsed["interval"], action=act)
    return f"Recurring task set ({jid}), first {_fmt_eta(parsed['fire_at'])}."


@register_tool(
    name="list_reminders",
    description="List active reminders and recurring tasks.",
    category="scheduler",
)
def list_reminders() -> str:
    """List all active scheduled jobs."""
    jobs = scheduler.list_jobs()
    if not jobs:
        return "You have no active reminders or scheduled tasks."
    parts = [f"({j['id']}) {j['text']} — {_fmt_eta(j['fire_at'])}" for j in jobs[:10]]
    return "Your scheduled items: " + "; ".join(parts) + "."


@register_tool(
    name="cancel_reminder",
    description="Cancel a reminder or recurring task by its number (from list_reminders).",
    category="scheduler",
)
def cancel_reminder(reminder_id: int) -> str:
    """Cancel a scheduled job by id."""
    return (
        f"Cancelled reminder {reminder_id}."
        if scheduler.cancel(reminder_id)
        else f"I couldn't find an active reminder with id {reminder_id}."
    )
