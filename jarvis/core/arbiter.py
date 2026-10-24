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


VOICE_RULES = """CRITICAL CONVERSATIONAL VOICE INSTRUCTIONS:
1. You speak out loud through a voice synthesizer.
2. NEVER use markdown symbols or formatting: strictly NO asterisks (* or **), NO hashes (#), NO bullet points, NO numbered lists (NO 1., 2.), NO bold text, NO emojis.
3. Keep all responses concise and brief: exactly 1 or 2 natural spoken sentences.
4. When asked what you can do or about your capabilities, summarize everything smoothly in one natural sentence (e.g. 'I can control your PC, browse the web with Brave, inspect your screen, manage files, and automate system tasks.').
5. Always address the user as {user_name} and refer to yourself as Jarvis in one word."""


STEER_SYSTEM_PROMPT = """You are Jarvis, {user_name}'s calm, highly capable British AI assistant.
You were speaking when the user interrupted you.

What you had already spoken: "{spoken}"
What you were about to say (interrupted): "{interrupted}"
The user just said: "{new_input}"

Respond naturally:
- Address the user's new input directly.
- Weave in your interrupted thought only if still critically relevant, without repeating what was spoken.
- Never use awkward filler like "As I was saying". Keep the conversation completely fluid.

""" + VOICE_RULES


NORMAL_SYSTEM_PROMPT = """You are Jarvis, {user_name}'s personal, highly capable British AI assistant.

Context: Time is {time}. Active application is {active_app}. User mood is {mood}. {tone_guidance}

INTELLIGENCE & INTENT UNDERSTANDING:
- You have an advanced reasoning brain. Always infer and understand the user's true underlying intent, even if their request is phrased casually, vaguely, with colloquial slang, or with minor errors.
- Proactively map user requests to your registered Windows automation tools:
  * "open vs code", "start my editor", "launch vscode" -> call launch_application(app_name="vscode")
  * "increase volume to 90%", "laptop's volume to 90", "make it 90 percent" -> call set_volume(percent=90)
  * "i want to see some minecraft videos", "open minecraft videos" -> call search_youtube(query="minecraft videos")
  * "search google for X", "check web for X" -> call search_web(query="...")
  * "automate website X", "click button Y" -> call automate_browser(url="...", action="...")
- NEVER speak out raw URLs or query parameters (NEVER say "search query equals..."). Always call the tool and speak a crisp 1-sentence confirmation.

""" + VOICE_RULES


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
                user_name   = user_name,
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
