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


from jarvis.core.memory import memory_manager

# Persona styles selected by config [jarvis].personality.
PERSONALITY_STYLES = {
    "calm_professional": "Calm, composed and professional — precise, reassuring, minimal filler.",
    "witty": "Witty and lightly humorous with clever quips, while staying genuinely helpful.",
    "formal": "Formal and refined, with courteous, measured phrasing.",
    "casual": "Relaxed, friendly and conversational — warm and easy-going.",
}


def _personality_guidance() -> str:
    try:
        from jarvis.core.config import load_config
        p = (load_config().get("jarvis", {}).get("personality") or "calm_professional").lower()
    except Exception:
        p = "calm_professional"
    return PERSONALITY_STYLES.get(p, PERSONALITY_STYLES["calm_professional"])

VOICE_RULES = """CRITICAL CONVERSATIONAL VOICE INSTRUCTIONS:
1. You speak out loud through a voice synthesizer.
2. NEVER use markdown symbols or formatting: strictly NO asterisks (* or **), NO hashes (#), NO bullet points, NO numbered lists (NO 1., 2.), NO bold text, NO emojis.
3. Keep all responses concise and brief: exactly 1 or 2 natural spoken sentences.
4. When asked what you can do or about your capabilities, summarize everything smoothly in one natural sentence (e.g. 'I can control your PC, browse the web with Brave, inspect your screen, manage files, and automate system tasks.').
5. Address the user as {user_name} and refer to yourself as Jarvis in one word."""


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
Persona: {personality}

PERSISTENT USER PROFILE & KNOWN FACTS:
{facts}

INTELLIGENCE & ZERO-KEYWORD INTENT UNDERSTANDING:
- You have an advanced reasoning brain like ChatGPT. Always infer and understand the user's true underlying intent, even if their request is phrased casually, vaguely, with colloquial slang, or with minor phonetic slips.
- SPEECH ACCENT & HOMOPHONE CORRECTION:
  * "compose a male" / "send a male" / "write a male" ALWAYS means "compose a mail" / "email" -> call compose_email()
  * "open V.S. code" / "V S code" means "vs code" -> call launch_application(app_name="vscode")
  * "open Blender" -> call launch_application(app_name="blender")
  * "open Dreams channel" -> call search_youtube(query="Dreams channel")
  * "open his most watched video" / "most watched video of Brem/Dream" -> call play_youtube_video(query="Dream most watched video")
  * "open the first video" / "click first video" / "select the first video" -> call click_active_video(index=1)
  * "increase volume" / "make it louder" -> call change_volume_relative(delta_percent=10)
  * "decrease volume" / "turn down sound" -> call change_volume_relative(delta_percent=-10)
  * "which application am I in" / "what app is open" -> call get_current_active_window()
  * "send a message on academic group" / "message on what-up" -> call send_whatsapp_message(chat_name="academic group", message="...")
  * "read messages on whatsapp" / "read chat" -> call read_whatsapp_messages(chat_name="...")
  * "add stitch MCP" / "stitch McB" -> call add_mcp_server(name="stitch")
- ACTION BIAS: When the user asks you to open an application, play a video, click on something, message someone, or perform any action, NEVER just talk about it or say 'Sure, I will do it'. You MUST call the corresponding tool immediately!
- Proactively map user requests to your registered Windows automation & MCP tools:
  * "open vs code", "start my editor", "launch vscode", "open brave" -> call launch_application(app_name="...")
  * "increase volume to 90%", "laptop's volume to 90", "make it 90 percent" -> call set_volume(percent=90)
  * "i want to see some minecraft videos", "open minecraft videos" -> call search_youtube(query="minecraft videos")
  * "search google for X", "check web for X" -> call search_web(query="...")
  * "automate website X", "click button Y" -> call automate_browser(url="...", action="...")
  * "remember my name is Om", "call me Om", "remember that I prefer dark mode" -> call save_user_memory(fact="...")
  * "what do you know about me", "recall my preferences" -> call recall_user_memories(query="...")
  * "what can you do", "what are your functionalities" -> call get_jarvis_capabilities()
  * "read pdf/doc X", "summarize document X" -> call read_document_markitdown(file_path="...")
  * "find function X in my code", "search codebase for Y" -> call codebase_search_context(query="...")
  * "take a screenshot and show me", "put up the screenshot" -> call capture_screen(show_image=True)
  * "inspect screen", "tell me what is on my screen" -> call inspect_screen()
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

        actual_user = user_name if user_name and user_name != "Sir" else memory_manager.user_name
        facts_summary = memory_manager.get_facts_summary()

        if ctx and ctx.was_interrupted and ctx.interrupted_text:
            # ── STEER PATH — context stitching ───────────────────────────
            ctx.new_user_input = new_user_input
            system = STEER_SYSTEM_PROMPT.format(
                user_name   = actual_user,
                spoken      = ctx.spoken_text     or "(nothing yet)",
                interrupted = ctx.interrupted_text,
                new_input   = new_user_input,
            )
            user_msg = new_user_input
            logger.debug("[STEER] Using steer-stitched prompt.")
        else:
            # ── NORMAL PATH ──────────────────────────────────────────────
            system = NORMAL_SYSTEM_PROMPT.format(
                user_name     = actual_user,
                time          = current_time,
                active_app    = active_app,
                mood          = mood,
                tone_guidance = tone_guidance,
                personality   = _personality_guidance(),
                facts         = facts_summary,
            )
            user_msg = new_user_input

        # Clear steer context after use
        with self._lock:
            self._context = None

        return system, user_msg
