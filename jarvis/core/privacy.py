"""
J.A.R.V.I.S. — Privacy-aware model routing

Decides whether a turn may be answered by a CLOUD model (fast, high quality) or
must stay on the LOCAL model (private). The rule is deliberately conservative:

  Cloud is allowed ONLY when the turn offers no tools (small talk or a general
  question) AND the text references nothing private. That guarantees a cloud
  turn never executes a PC tool and never carries file/screen/credential/memory
  context — so your personal data never leaves the machine.

Everything else — any command that uses a tool, anything about your files,
screen, credentials, memory, schedule, or PC state — runs locally.
"""
from __future__ import annotations

import re

from jarvis.tools.knowledge import looks_private as _looks_private

# References to the user's own data / machine / assistant memory → keep local.
_PRIVATE = re.compile(
    r"\b(my|mine|myself|remember|remind me|recall|forget|"
    r"what did i|who am i|my name|call me|"
    r"password|passwords|credential|credentials|secret|secrets|vault|login|sign ?in|sign ?up|"
    r"file|files|folder|folders|directory|document|documents|downloads|desktop|"
    r"screen|screenshot|clipboard|"
    r"email|inbox|calendar|schedule|reminder|reminders|meeting|meetings|"
    r"volume|brightness|battery|cpu|gpu|ram|wifi|ip address|"
    r"this (?:code|file|project|screen|document|window))\b",
    re.I,
)


def is_private(text: str) -> bool:
    """True if the utterance references private/local data or the user's PC/memory."""
    if not text:
        return True
    if _looks_private(text):
        return True
    return bool(_PRIVATE.search(text))


def allow_cloud(text: str, tools_offered: bool) -> bool:
    """
    Cloud is permitted only for no-tool, non-private turns (small talk / general
    knowledge). Any tool use or private reference forces the local model.
    """
    if tools_offered:
        return False
    return not is_private(text)
