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
import re
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
from jarvis.core.memory   import memory_manager
from jarvis.tools.screen_tool import ScreenTool
from jarvis.audio.speaker_id import speaker_id
import jarvis.tools  # Automatically registers all tools & plugins
from jarvis.tools.registry import registry
from jarvis.tools.router   import ToolRouter
from jarvis.core.agent_loop import AgentLoop
from jarvis.audio.accent_normalizer import SpeechNormalizer


class JarvisPipeline:
    """
    The top-level orchestrator.
    All components are owned here and communicate via callbacks and events.
    """

    def __init__(self):
        self._cfg         = load_config()
        self._running     = False

        # ── Component instances ──────────────────────────────────────────
        self.stt         = STTEngine()
        self.tts         = TTSEngine()
        self.mood        = MoodEngine()
        self.llm         = OllamaClient()
        self.arbiter     = SteerArbiter(self.tts, self.llm)
        self.screen_tool = ScreenTool()
        self.tool_router = ToolRouter()
        self.agent_loop  = AgentLoop(self.llm, speak_fn=self._speak_async)
        self.speaker_id  = speaker_id
        self.vad         = VADListener(
            on_speech_segment=self._on_speech_segment,
            is_speaking_fn=lambda: self.tts.is_speaking,
            speaker_verifier_fn=lambda audio: self.speaker_id.verify(audio, threshold=0.62)[0] if self.speaker_id._enrolled_speakers else True,
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
        self._user_name            = memory_manager.user_name or self._cfg["jarvis"]["user_name"]

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

        # 2. Load STT model on CUDA first (establishes fixed audio memory footprint)
        logger.info("Loading STT model...")
        await asyncio.to_thread(self.stt.load)

        # 3. Pre-warm fast LLM with exact 4096 context into remaining GPU VRAM
        await self.llm.warm_up()

        # 3. Load TTS model
        logger.info("Loading TTS model...")
        await asyncio.to_thread(self.tts.load)

        # 4. Start VAD listener and arm real-time voice barge-in
        logger.info("Starting VAD listener...")
        self.vad.start()
        self.vad.enable_barge_in(self._on_barge_in)

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
            self.agent_loop.cancel()

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
        self.agent_loop.cancel()
        self._listening = True
        self._listening_timestamp = time.time()

    async def _handle_screen_request(self) -> str:
        """Capture desktop screen and extract real active window, process, and OCR content."""
        try:
            img_path = await asyncio.to_thread(self.screen_tool.capture_screen, False)
            active_title = "Desktop"
            try:
                import win32gui
                hwnd = win32gui.GetForegroundWindow()
                title = win32gui.GetWindowText(hwnd)
                if title and title.strip():
                    active_title = title.strip()
            except Exception:
                pass

            # Extract actual on-screen text with native Windows Media OCR (<30ms)
            ocr_lines = await self.screen_tool.extract_screen_text(img_path)
            ocr_summary = " | ".join(ocr_lines[:30]) if ocr_lines else "Active desktop view"

            return (
                f"[LIVE DESKTOP SCREEN CONTEXT]:\n"
                f"- Screenshot captured and saved to: {img_path.name}\n"
                f"- Active foreground window in focus: '{active_title}'\n"
                f"- On-screen text and elements: {ocr_summary}\n"
                f"Instruction: Confirm you captured the screen, and concisely tell {self._user_name} what they currently have open and visible on screen in 1 or 2 natural spoken sentences."
            )
        except Exception as e:
            logger.warning(f"Screen capture notice: {e}")
            return "[LIVE DESKTOP SCREEN CONTEXT]: Screenshot captured."

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

            text = SpeechNormalizer.normalize(text)

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

            # Ignore brief hesitations ("um", "uh", "ah") without destroying the listening window
            clean_cmd = text.strip().lower().rstrip(".,!?")
            if is_armed and (clean_cmd in {"um", "uh", "ah", "hmm", "er", "oh", "like"} or len(clean_cmd) < 2):
                logger.debug(f"Hesitation '{text}' ignored; keeping 15s follow-up window open.")
                return

            if len(text.strip()) < 2:
                return

            # Consume the active armed token for this command
            self._listening = False
            logger.info(f"👤 User: {text}")

            # ── Speaker Verification & Voice Enrollment ───────────────────
            clean_lower = text.lower().strip().rstrip(".!?")

            # Check for zero-keyword natural voice enrollment intent:
            # Matches "I want to register my voice and you will follow commands from only that voice",
            # "learn my voice", "register my voice", "listen only to my voice", "save my voice profile", etc.
            VOICE_ENROLLMENT_PATTERNS = [
                r"(?:register|enroll|learn|save|remember|record|train|set\s*up)\s+(?:my|the)\s+voice",
                r"(?:follow|listen\s+to|respond\s+to|take\s+commands\s+from)\s+(?:only|just)\s+(?:from\s+)?my\s+voice",
                r"voice\s+(?:profile|biometrics|recognition|identification)",
                r"(?:recognize|identify)\s+my\s+voice",
                r"(?:only\s+)?(?:follow|obey|respond\s+to)\s+(?:commands\s+from\s+)?(?:only\s+)?me",
                r"want\s+(?:you\s+to\s+)?(?:register|learn|recognize|save)\s+my\s+voice",
            ]
            if any(re.search(pat, clean_lower) for pat in VOICE_ENROLLMENT_PATTERNS):
                logger.info("🎙️ Enrolling user voiceprint from spoken speech...")
                enrolled = self.speaker_id.enroll(self._user_name, audio)
                if enrolled:
                    memory_manager._profile["voice_enrolled"] = True
                    memory_manager._profile["registered_speaker"] = self._user_name
                    memory_manager.save_profile()
                    resp = f"Voiceprint registered successfully, {self._user_name}. I have memorized your acoustic profile and will now only follow and respond to your voice."
                else:
                    resp = f"I could not capture a clear voice sample, {self._user_name}. Please try speaking a slightly longer sentence."
                await self._speak_async(resp)
                self._listening = True
                self._listening_timestamp = time.time()
                return

            # Direct name registration ("remember my name is Om", "call me Om", "my name is Om")
            name_m = re.search(r"(?:remember\s+(?:that\s+)?)?(?:my\s+name\s+is|call\s+me)\s+([a-zA-Z]+)", clean_lower)
            if name_m:
                new_name = name_m.group(1).title()
                self._user_name = new_name
                memory_manager.set_user_name(new_name)
                resp = f"It is a pleasure, {new_name}. I have committed your name to memory and will address you accordingly."
                await self._speak_async(resp)
                self._listening = True
                self._listening_timestamp = time.time()
                return

            if self.speaker_id._enrolled_speakers:
                is_auth, sim, name = self.speaker_id.verify(audio, threshold=0.66)
                if not is_auth:
                    logger.warning(f"🛡️ Speech ignored: Unrecognized voice (similarity={sim:.2f} < 0.66). Authorized only for {self._user_name}.")
                    return
                logger.debug(f"👤 Verified speaker: {name} (similarity={sim:.2f})")

            # ── 1. Fast-path intent check (< 1ms instant OS execution) ────
            fast_resp = await self.tool_router.try_fast_path(text)
            if fast_resp:
                logger.info(f"⚡ Fast-path action executed: {fast_resp}")
                await self._speak_async(fast_resp)
                self._listening = True
                self._listening_timestamp = time.time()
                self._conversation_history.extend([
                    {"role": "user",      "content": text},
                    {"role": "assistant", "content": fast_resp},
                ])
                return

            # Check for screen / vision command
            lower_query = text.lower()
            screen_keywords = ["screenshot", "screen", "what do you see", "look at my screen", "what's on my screen", "what is on my screen", "see my screen", "read my screen"]
            if any(k in lower_query for k in screen_keywords):
                logger.info("📸 Screen inspection requested. Capturing desktop context...")
                screen_ctx = await self._handle_screen_request()
                text = f"{text}\n\n{screen_ctx}"

            # ── 2. Mood analysis (zero-latency background update) ─────────
            mood_state = self.mood.current_mood
            asyncio.create_task(asyncio.to_thread(self.mood.analyze, audio))

            # ── 3. Build prompt (steer-aware + tools schema) ──────────────
            try:
                import win32gui
                hwnd = win32gui.GetForegroundWindow()
                if hwnd:
                    fg_title = win32gui.GetWindowText(hwnd)
                    if fg_title and fg_title.strip():
                        self._active_app = fg_title.strip()
            except Exception:
                pass

            system_prompt, user_msg = self.arbiter.build_prompt(
                new_user_input = text,
                user_name      = self._user_name,
                current_time   = datetime.datetime.now().strftime("%H:%M"),
                active_app     = self._active_app,
                mood           = mood_state.mood,
                tone_guidance  = mood_state.tone_guidance,
            )
            # Inject dynamic registered tool capabilities for LLM
            system_prompt += self.tool_router.get_tool_prompt_section()

            # ── 4. Stream LLM response → TTS ─────────────────────────────
            self._cancel_llm.clear()
            response_buffer = []

            async def stream_to_tts():
                """Stream tokens, detect tool calls, and speak in natural chunks."""
                pending = ""
                is_tool_call_stream = False

                async for token in self.llm.stream(
                    system_prompt = system_prompt,
                    user_message  = user_msg,
                    history       = self._conversation_history[-self._max_history:],
                    cancel_event  = self._cancel_llm,
                ):
                    response_buffer.append(token)
                    pending += token

                    accumulated = "".join(response_buffer).strip()
                    if "TOOL_CALL:" in accumulated or accumulated.startswith("TOOL_"):
                        is_tool_call_stream = True

                    # If this is regular conversational text, stream sentence-by-sentence to TTS
                    if not is_tool_call_stream:
                        if any(pending.rstrip().endswith(p) for p in [".", "!", "?"]):
                            clean_candidate = pending.strip()
                            if len(clean_candidate) >= 15 and not clean_candidate.endswith(("Mr.", "Dr.", "e.g.", "vs.", "i.e.")):
                                sentence = clean_candidate
                                pending = ""
                                if sentence:
                                    logger.debug(f"🤖 Jarvis: {sentence}")
                                    await asyncio.to_thread(self.tts.speak, sentence, False)

                # Process end of stream
                full_resp = "".join(response_buffer).strip()
                if is_tool_call_stream:
                    logger.info(f"🤖 Multi-step / tool workflow initiated via AgentLoop for: '{text}'")
                    spoken_confirm = await self.agent_loop.run(
                        user_request=text,
                        user_name=self._user_name,
                        current_time=datetime.datetime.now().strftime("%H:%M"),
                        active_app=self._active_app,
                        mood=mood_state.mood,
                        conversation_history=self._conversation_history,
                    )
                    if spoken_confirm and not self._cancel_llm.is_set():
                        logger.info(f"🤖 Jarvis: {spoken_confirm}")
                        await asyncio.to_thread(self.tts.speak, spoken_confirm, False)
                    response_buffer.clear()
                    response_buffer.append(spoken_confirm)
                elif pending.strip() and not self._cancel_llm.is_set():
                    await asyncio.to_thread(self.tts.speak, pending.strip(), False)

            await stream_to_tts()

            # Keep listening open for 15 seconds for seamless conversational follow-ups
            self._listening = True
            self._listening_timestamp = time.time()
            logger.info("🎙️ Jarvis is standing by for follow-up questions (15s)...")

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
