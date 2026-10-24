"""
J.A.R.V.I.S. — Main Orchestration Pipeline
The central loop that connects every module into a coherent voice assistant.

Startup sequence:
  1. Load config
  2. Start Ollama health check
  3. Load STT + TTS models
  4. Start VAD + Trigger system
  5. Enter the main event loop

Runtime flow:
  Wake/Hotkey → VAD → STT → Mood → Arbiter → LLM → TTS → (repeat)
"""
from __future__ import annotations

import asyncio
import datetime
import threading
import time
from pathlib import Path
from typing import Optional

from loguru import logger

from jarvis.audio.trigger import TriggerSystem
from jarvis.audio.vad     import VADListener
from jarvis.audio.stt     import STTEngine
from jarvis.audio.tts     import TTSEngine
from jarvis.audio.mood    import MoodEngine
from jarvis.brain.ollama_client import OllamaClient
from jarvis.core.arbiter  import SteerArbiter
from jarvis.core.config   import load_config


class JarvisPipeline:
    """
    The top-level orchestrator.
    All components are owned here and communicate via callbacks and events.
    """

    def __init__(self):
        self._cfg         = load_config()
        self._running     = False

        # ── Component instances ──────────────────────────────────────────
        self.stt     = STTEngine()
        self.tts     = TTSEngine()
        self.mood    = MoodEngine()
        self.llm     = OllamaClient()
        self.arbiter = SteerArbiter(self.tts, self.llm)
        self.vad     = VADListener(
            on_speech_segment=self._on_speech_segment,
            is_speaking_fn=lambda: self.tts.is_speaking,
        )
        self.trigger = TriggerSystem(
            on_trigger=self._on_trigger_fired,
            on_mode_change=self._on_wake_mode_changed,
        )

        # ── State ────────────────────────────────────────────────────────
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._listening            = False     # True when actively recording user speech
        self._listening_timestamp  = 0.0
        self._cancel_llm           = asyncio.Event()
        self._conversation_history: list  = []
        self._max_history          = self._cfg["memory"]["max_l1_turns"] * 2  # user+assistant turns
        self._user_name            = self._cfg["jarvis"]["user_name"]

        # Active application context (updated by system monitor)
        self._active_app = "Desktop"

        # ── Wire HUD callbacks (set externally when HUD is ready) ────────
        self.tts.on_speaking_start = None
        self.tts.on_speaking_stop  = None

        logger.info("JarvisPipeline initialized.")

    # ──────────────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────────────

    async def start(self):
        """Full startup sequence — call this from main.py."""
        self._loop = asyncio.get_running_loop()
        logger.info("=" * 60)
        logger.info("  J.A.R.V.I.S. — Starting up...")
        logger.info("=" * 60)

        # 1. Verify Ollama is running
        logger.info("Checking Ollama health...")
        healthy = await self.llm.check_health()
        if not healthy:
            logger.error(
                "Ollama is not running or fast model is not available.\n"
                f"Please start Ollama and ensure '{self.llm._fast_model}' is pulled."
            )
            raise RuntimeError("Ollama not available.")

        # Pre-warm fast model in GPU VRAM for instant < 200ms response
        await self.llm.warm_up()

        # 2. Load STT model
        logger.info("Loading STT model...")
        await asyncio.to_thread(self.stt.load)

        # 3. Load TTS model
        logger.info("Loading TTS model...")
        await asyncio.to_thread(self.tts.load)

        # 4. Start VAD listener
        logger.info("Starting VAD listener...")
        self.vad.start()

        # 5. Start trigger system (wake word + hotkey)
        logger.info("Starting trigger system...")
        self.trigger.start()

        self._running = True
        logger.success("✅ Jarvis is online and listening.")

        # Greeting (pronounce Jarvis naturally as a single word)
        hotkey_str = "+".join(self._cfg.get("hotkey", {}).get("trigger_keys", ["win", "j"]))
        await self._speak_async(
            f"Good {self._time_of_day()}, {self._user_name}. "
            f"Jarvis is online and ready. "
            f"Wake word and {hotkey_str} hotkey are active."
        )

        # 6. Main event loop — keeps process alive
        try:
            while self._running:
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    async def stop(self):
        self._running = False
        self.vad.stop()
        self.trigger.stop()
        logger.info("Jarvis shut down.")

    # ──────────────────────────────────────────────────────────────────
    # Trigger & speech event handlers
    # ──────────────────────────────────────────────────────────────────

    def _on_trigger_fired(self):
        """Called from trigger thread when wake word or hotkey fires."""
        if self.tts.is_speaking:
            logger.info("🛑 Hotkey pressed during speech — interrupting playback.")
            self.tts.interrupt()
            self._cancel_llm.set()

        self._listening = True
        self._listening_timestamp = time.time()
        logger.info("🎙️ Listening armed via hotkey (Win+J). Jarvis is listening for 15s...")

    def _on_wake_mode_changed(self, enabled: bool):
        """Spoken notification when wake word is toggled live via Win+Shift+J."""
        msg = "Wake word listening enabled." if enabled else "Wake word disabled. Hotkey mode active."
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._speak_async(msg), self._loop)

    def _on_speech_segment(self, audio):
        """Called by VAD when a complete speech segment is ready."""
        # Never process speech if Jarvis is speaking
        if self.tts.is_speaking:
            return
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._process_speech(audio),
                self._loop,
            )

    def _on_barge_in(self):
        """Called when user explicitly interrupts."""
        self.arbiter.on_barge_in()
        self._cancel_llm.set()
        self._listening = True
        self._listening_timestamp = time.time()

    # ──────────────────────────────────────────────────────────────────
    # Core processing pipeline
    # ──────────────────────────────────────────────────────────────────

    async def _process_speech(self, audio):
        """Full pipeline: audio → STT → Mood → Arbiter → LLM → TTS."""
        try:
            if self.tts.is_speaking:
                return

            # ── 1. Transcribe ────────────────────────────────────────────
            text = await asyncio.to_thread(self.stt.transcribe, audio)
            if not text or not text.strip():
                return

            now = time.time()
            # Active listening window: 15 seconds after hotkey, wake response, or follow-up
            is_armed = self._listening and (now - self._listening_timestamp < 15.0)

            # Check trigger conditions: armed by hotkey/follow-up OR explicit wake phrase
            if is_armed:
                text = self.trigger.strip_wake_word(text)
            else:
                if self.trigger.wake_word_enabled and self.trigger.is_wake_word(text):
                    logger.success(f"🎙️  Wake word recognized in: '{text}'")
                    command_text = self.trigger.strip_wake_word(text).strip()
                    if not command_text or len(command_text) < 2:
                        # User said ONLY the wake word (e.g. "Hey Jarvis")
                        await self._speak_async(f"At your service, {self._user_name}.")
                        self._listening = True
                        self._listening_timestamp = time.time()
                        logger.info(f"🎙️ Jarvis active for 15s. Awaiting your command, {self._user_name}...")
                        return
                    else:
                        # User said wake word + command together
                        text = command_text
                else:
                    logger.debug(f"Ambient speech ignored (standby mode): '{text}'")
                    return

            if not text.strip():
                return

            # Consume the active armed token for this command
            self._listening = False
            logger.info(f"👤 User: {text}")

            # ── 2. Mood analysis (non-blocking, runs in parallel) ─────────
            mood_state = await asyncio.to_thread(self.mood.analyze, audio)

            # ── 3. Build prompt (steer-aware) ────────────────────────────
            system_prompt, user_msg = self.arbiter.build_prompt(
                new_user_input = text,
                user_name      = self._user_name,
                current_time   = datetime.datetime.now().strftime("%H:%M"),
                active_app     = self._active_app,
                mood           = mood_state.mood,
                tone_guidance  = mood_state.tone_guidance,
            )

            # ── 4. Stream LLM response → TTS ─────────────────────────────
            self._cancel_llm.clear()
            response_buffer = []

            async def stream_to_tts():
                """Stream tokens and speak in natural sentence chunks."""
                pending = ""
                async for token in self.llm.stream(
                    system_prompt = system_prompt,
                    user_message  = user_msg,
                    history       = self._conversation_history[-self._max_history:],
                    cancel_event  = self._cancel_llm,
                ):
                    response_buffer.append(token)
                    pending += token

                    # Speak sentence-by-sentence as tokens arrive
                    if any(pending.rstrip().endswith(p) for p in [".", "!", "?"]):
                        clean_candidate = pending.strip()
                        # Avoid splitting on common abbreviations
                        if len(clean_candidate) >= 15 and not clean_candidate.endswith(("Mr.", "Dr.", "e.g.", "vs.", "i.e.")):
                            sentence = clean_candidate
                            pending  = ""
                            if sentence:
                                logger.debug(f"🤖 Jarvis: {sentence}")
                                await asyncio.to_thread(
                                    self.tts.speak, sentence, False
                                )

                # Speak any remaining fragment
                if pending.strip() and not self._cancel_llm.is_set():
                    await asyncio.to_thread(self.tts.speak, pending.strip(), False)

            await stream_to_tts()

            # Keep listening open for 10 seconds for seamless conversational follow-ups
            self._listening = True
            self._listening_timestamp = time.time()
            logger.debug("🎙️ Conversation window open (10s follow-up)...")

            # ── 5. Update conversation history ───────────────────────────
            if response_buffer:
                full_response = "".join(response_buffer)
                self._conversation_history.extend([
                    {"role": "user",      "content": text},
                    {"role": "assistant", "content": full_response},
                ])
                # Trim history to max window
                if len(self._conversation_history) > self._max_history:
                    self._conversation_history = \
                        self._conversation_history[-self._max_history:]

        except Exception as e:
            logger.exception(f"Pipeline error: {e}")
            await self._speak_async("I encountered an error. Please try again.")

    # ──────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────

    async def _speak_async(self, text: str):
        """Speak text asynchronously without blocking the event loop."""
        await asyncio.to_thread(self.tts.speak, text)

    def _time_of_day(self) -> str:
        hour = datetime.datetime.now().hour
        if hour < 12:  return "morning"
        if hour < 17:  return "afternoon"
        if hour < 21:  return "evening"
        return "night"
