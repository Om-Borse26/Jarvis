"""
J.A.R.V.I.S. — Steer & Interruption Arbiter
The core of the "Iron Man feel" — handles barge-in and context stitching.
When the user interrupts Jarvis mid-sentence, this module:
  1. Captures what was already spoken vs. what was cut off
  2. Stitches a context-aware prompt so Jarvis resumes naturally
"""
from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import Optional, Callable

from loguru import logger


@dataclass
class SteerContext:
    """Holds the state of an interrupted Jarvis response."""
    spoken_text:      str = ""    # What Jarvis already said out loud
    interrupted_text: str = ""    # What Jarvis was about to say
    new_user_input:   str = ""    # The user's new utterance
    was_interrupted:  bool = False


STEER_SYSTEM_PROMPT = """You are J.A.R.V.I.S., an intelligent AI assistant.
You were in the middle of speaking when the user interrupted you.

What you had already spoken: "{spoken}"
What you were about to say (now interrupted): "{interrupted}"
The user just said: "{new_input}"

Respond naturally and fluidly:
- First, briefly acknowledge or address the user's new input directly.
- If any part of your interrupted thought is still critically relevant, weave it in naturally — don't repeat anything already spoken.
- If the interrupted thought is no longer relevant, drop it gracefully.
- Do NOT say "As I was saying..." or similar awkward phrases. Just speak naturally.
- Keep the same calm, confident Jarvis personality throughout."""

NORMAL_SYSTEM_PROMPT = """You are J.A.R.V.I.S. (Just A Rather Very Intelligent System), {user_name}'s personal AI assistant.

Current context:
- Time: {time}
- Active application: {active_app}
- User mood: {mood}

Tone guidance: {tone_guidance}

You have access to tools for controlling the PC, browsing the web, managing files, and more.
When using tools, briefly narrate what you are doing (e.g., "Opening Brave now", "Searching for that...").
Be direct, capable, and personable. Never verbose unless asked for detail."""


class SteerArbiter:
    """
    Manages the interruption-and-steer lifecycle between the TTS, STT, and LLM.

    Flow:
        User speaks (barge-in detected)
            → TTS.interrupt() called
            → Arbiter captures spoken_text / interrupted_text from TTS
            → STT transcribes new user input
            → build_steer_prompt() creates context-stitched prompt
            → LLM receives stitched prompt → continues naturally
    """

    def __init__(self, tts, llm_client):
        """
        Args:
            tts:        TTSEngine instance
            llm_client: OllamaClient instance
        """
        self._tts         = tts
        self._llm         = llm_client
        self._context:    Optional[SteerContext] = None
        self._lock        = threading.Lock()

    def on_barge_in(self):
        """Called immediately when VAD detects the user speaking during TTS."""
        with self._lock:
            if self._tts.is_speaking:
                # Interrupt playback instantly
                self._tts.interrupt()
                self._context = SteerContext(
                    spoken_text      = self._tts.spoken_text,
                    interrupted_text = self._tts.interrupted_text,
                    was_interrupted  = True,
                )
                logger.info(
                    f"[STEER] Barge-in captured. "
                    f"Spoken: '{self._context.spoken_text[:60]}' | "
                    f"Cut: '{self._context.interrupted_text[:60]}'"
                )

    def build_prompt(
        self,
        new_user_input: str,
        user_name: str      = "Sir",
        current_time: str   = "",
        active_app: str     = "Unknown",
        mood: str           = "neutral",
        tone_guidance: str  = "Be crisp and direct.",
    ) -> tuple[str, str]:
        """
        Build the (system_prompt, user_message) pair for the LLM.

        Returns:
            (system_prompt, user_message) — pass both to the LLM client.
        """
        with self._lock:
            ctx = self._context

        if ctx and ctx.was_interrupted and ctx.interrupted_text:
            # ── STEER PATH — context stitching ───────────────────────────
            ctx.new_user_input = new_user_input
            system = STEER_SYSTEM_PROMPT.format(
                spoken      = ctx.spoken_text     or "(nothing yet)",
                interrupted = ctx.interrupted_text,
                new_input   = new_user_input,
            )
            user_msg = new_user_input
            logger.debug("[STEER] Using steer-stitched prompt.")
        else:
            # ── NORMAL PATH ──────────────────────────────────────────────
            system = NORMAL_SYSTEM_PROMPT.format(
                user_name     = user_name,
                time          = current_time,
                active_app    = active_app,
                mood          = mood,
                tone_guidance = tone_guidance,
            )
            user_msg = new_user_input

        # Clear steer context after use
        with self._lock:
            self._context = None

        return system, user_msg
