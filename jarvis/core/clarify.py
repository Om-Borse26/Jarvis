"""
J.A.R.V.I.S. — Deterministic Slot Clarification
Detects commands that are missing a required piece of information and returns
a concise clarifying question — WITHOUT asking the weak local model to figure
it out. A 7B model under latency pressure tends to either hallucinate a value
or ramble; deterministic slot detection keeps clarification instant and exact.

Runs AFTER the fast-path router (so complete deterministic commands are already
handled) and BEFORE the model call. Returns None when nothing is missing.
"""
from __future__ import annotations

import re
from typing import Optional

# Words that indicate a time was supplied for a reminder/timer.
_TIME_HINT = re.compile(
    r"\b(in|at|after|every|tomorrow|tonight|today|morning|afternoon|evening|"
    r"night|noon|midnight|minute|minutes|hour|hours|second|seconds|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d)\b"
)


def missing_slot_question(text: str) -> Optional[str]:
    """Return a clarifying question if a required slot is missing, else None."""
    if not text:
        return None
    t = text.lower().strip()

    # Reminder / timer / alarm without a time.
    if re.search(r"\b(remind me|set (?:a |an )?(?:reminder|timer|alarm))\b", t):
        if not _TIME_HINT.search(t):
            return "When would you like me to remind you, Sir?"

    # Search / lookup with no query text after the verb.
    m = re.search(r"\b(search(?: the web| online| for)?|google|look up|youtube)\b", t)
    if m:
        tail = t[m.end():]
        tail = re.sub(r"^\s*(?:for|up|the|a|an|on|about|some)\b", "", tail).strip(" ?.")
        if not tail:
            return "What would you like me to search for, Sir?"

    # Write/compose a text artifact with no topic.
    if re.search(r"\b(write|compose|draft|generate)\b", t) and \
       re.search(r"\b(essay|paragraph|poem|story|article|blog|letter|report)\b", t):
        if not re.search(r"\b(about|on|regarding|for|titled|called)\b", t):
            return "What should it be about, Sir?"

    # Send a message with no recipient.
    if re.search(r"\b(send (?:a |an )?(?:message|text|whatsapp)|whatsapp|text|message)\b", t):
        if not re.search(r"\bto\b", t):
            return "Who should I send it to, Sir?"

    # Bare launch/focus verb with no application named.
    if re.fullmatch(r"(?:please\s+)?(?:open|launch|start|switch to|focus(?: on)?|show me)\s*", t):
        return "Which application, Sir?"

    return None
