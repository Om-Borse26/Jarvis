"""
J.A.R.V.I.S. — Eve (Companion Agent)
Eve is Jarvis's sister assistant for your phone. For now she runs on the PC and
your phone talks to her over your local network (later she can live on-device).

Eve has:
  - her OWN short conversation memory (she's a separate persona), and
  - SHARED memory with Jarvis via the shared bus — so a task you give Eve while
    away is waiting for Jarvis when you're back, and notes Jarvis leaves for Eve
    reach your phone.

She uses the same local Ollama brain, with a warmer, briefer phone persona.
"""
from __future__ import annotations

import re
from collections import deque
from typing import Deque, Dict, List

from loguru import logger

from jarvis.core.config import load_config
from jarvis.memory.shared_bus import shared_bus

_PERSONA = (
    "You are Eve, the friendly phone companion and sister AI to Jarvis. "
    "You help {user} on the go. Keep replies warm, natural, and brief (1-3 sentences). "
    "You share memory with Jarvis on the PC: tasks captured here wait for Jarvis when {user} returns. "
    "Never use markdown or emojis."
)

# Phrases that mean "hand this to Jarvis on the PC".
_HANDOFF = re.compile(
    r"(tell jarvis|ask jarvis|when i('| a)m back|when i get back|on my (pc|computer|desktop)|remind me to)",
    re.IGNORECASE,
)


class EveCompanion:
    """A lightweight companion agent with its own memory + shared bus access."""

    def __init__(self) -> None:
        cfg = load_config().get("llm", {})
        self._host = cfg.get("ollama_host", "http://127.0.0.1:11434")
        self._model = cfg.get("fast_model", "qwen2.5-coder:7b")
        self._user = load_config().get("jarvis", {}).get("user_name", "Sir")
        self._history: Deque[Dict[str, str]] = deque(maxlen=12)

    def process(self, text: str) -> str:
        """Handle a message from the phone; may hand tasks off to Jarvis."""
        text = (text or "").strip()
        if not text:
            return "I'm here. What do you need?"

        handed_off = False
        if _HANDOFF.search(text):
            shared_bus.push_event("task", {"text": text}, target="jarvis")
            handed_off = True

        reply = self._generate(text)
        if handed_off:
            reply += " I'll make sure Jarvis has it when you're back."

        self._history.append({"role": "user", "content": text})
        self._history.append({"role": "assistant", "content": reply})
        return reply

    def _generate(self, text: str) -> str:
        try:
            import ollama
            messages = [{"role": "system", "content": _PERSONA.format(user=self._user)}]
            messages.extend(list(self._history)[-8:])
            messages.append({"role": "user", "content": text})
            resp = ollama.Client(host=self._host).chat(
                model=self._model,
                messages=messages,
                options={"num_ctx": 4096, "temperature": 0.6, "num_predict": 160},
            )
            content = resp.get("message", {}).get("content", "") if isinstance(resp, dict) else ""
            content = re.sub(r"<think>.*?</think>", "", content or "", flags=re.DOTALL).strip()
            return content or "Okay."
        except Exception as e:
            logger.warning(f"[Eve] generation failed: {e}")
            return "I'm having trouble reaching my brain right now, but I've noted that."

    # ── Shared tasks surfaced on the phone ────────────────────────────────────
    def pending_from_jarvis(self) -> List[dict]:
        return shared_bus.pending(target="eve", limit=20)

    def ack(self, event_id: int) -> None:
        shared_bus.ack(event_id)

    def note_for_jarvis(self, text: str) -> None:
        shared_bus.push_event("note", {"text": text}, target="jarvis")


# Process-wide singleton
eve = EveCompanion()
