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
from jarvis.brain.llm_provider import make_llm_client, make_cloud_client, is_hybrid
from jarvis.core.privacy import allow_cloud
from jarvis.core.arbiter  import SteerArbiter
from jarvis.core.config   import load_config
from jarvis.core.clarify  import missing_slot_question
from jarvis.core.intent_scope import select_tools
from jarvis.core.intent_dispatcher import intent_dispatcher
from jarvis.core.memory   import memory_manager
from jarvis.tools.screen_tool import ScreenTool
from jarvis.audio.speaker_id import speaker_id
import jarvis.tools  # Automatically registers all tools & plugins
from jarvis.tools.registry import registry
from jarvis.tools.router   import ToolRouter
from jarvis.core.agent_loop import AgentLoop
from jarvis.audio.accent_normalizer import SpeechNormalizer
from jarvis.security.consent import consent_manager
from jarvis.tools.mcp_runtime import mcp_manager
from jarvis.memory.working import working_memory
from jarvis.memory.episodic import episodic_memory
from jarvis.core.scheduler import scheduler
from jarvis.core import lifecycle
from jarvis.ui.state import state_bridge
from jarvis.ui.server import ControlServer


# Minimal persona prompt for cloud turns — carries NO private context on purpose.
CLOUD_CHAT_PROMPT = (
    "You are Jarvis, a calm, witty British AI assistant. Reply in one or two short, "
    "natural spoken sentences. Address the user as 'Sir'. You are chatting or answering "
    "a general question — do not mention tools, files, or the user's device."
)

SCREEN_CAPTURE_PAT = re.compile(
    r"\b(screenshot|capture (?:the |my )?screen|look at (?:the |my )?screen|"
    r"what(?:'s| is) on (?:the |my )?screen|see (?:the |my )?screen|"
    r"read (?:the |my )?screen|inspect (?:the |my )?screen|what do you see)\b",
    re.IGNORECASE,
)



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
        self.llm         = make_llm_client()
        # Cloud model for non-private turns only (privacy-aware routing).
        self.cloud_llm   = make_cloud_client() if is_hybrid() else None
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

        # Reminder queueing and barge-in continuation state
        self._is_processing_turn   = False
        self._pending_reminders: list[str] = []
        self._interrupted_summary  = ""

        # ── Wire HUD callbacks (set externally when HUD is ready) ────────
        self.tts.on_speaking_start = None
        self.tts.on_speaking_stop  = None

        # ── Interactive consent gate (voice confirmation for risky actions)
        self.consent = consent_manager
        self.consent.speak_fn = self._speak_async
        self.consent.arm_fn   = self._arm_listening

        # ── HUD (visual notifications + confirmation safety gate) ───────
        from jarvis.hud.manager import hud_manager
        self.hud = hud_manager
        self.consent.hud_fn = self.hud.request_confirmation
        self.consent.clear_hud_fn = self.hud.clear_confirmation
        self.hud.on_confirm_response = self.consent.resolve_threadsafe

        # ── Proactivity scheduler (reminders / recurring tasks) ─────────
        self.scheduler = scheduler
        self.scheduler.speak_fn   = self._on_scheduler_speak
        self.scheduler.command_fn = self._run_scheduled_command
        self.scheduler.notify_fn  = lambda title, body="": self.hud.notify(title, body)

        # ── UI: state bridge + control server (orb + dashboard) ─────────
        self._ui_server: Optional[ControlServer] = None
        self._eve_server = None
        self._island_proc = None
        self._hud_proc = None
        self.tts.on_speaking_start = lambda: state_bridge.set("speaking")
        self.tts.on_speaking_stop  = lambda: state_bridge.set("idle")

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

        # 6. Connect MCP servers in the background (non-blocking, best-effort)
        asyncio.create_task(self._start_mcp_servers())

        # 7. Start the proactivity scheduler (reminders, recurring tasks)
        self.scheduler.start()

        # 8. Start the system tray (background control), best-effort
        try:
            from jarvis.ui.tray import start_tray
            start_tray(on_stop=lifecycle.request_shutdown, on_dashboard=self._open_dashboard)
        except Exception as e:
            logger.debug(f"[Tray] not started: {e}")

        # 9. Start the UI control server + desktop orb (best-effort)
        self._start_ui()

        # 10. Start the Eve phone-companion sync server (best-effort)
        self._start_eve()

        self._running = True
        logger.success("✅ Jarvis is online and listening.")

        # Greeting (pronounce Jarvis naturally as a single word)
        hotkey_str = "+".join(self._cfg.get("hotkey", {}).get("trigger_keys", ["win", "j"]))
        await self._speak_async(
            f"Good {self._time_of_day()}, {self._user_name}. "
            f"Jarvis is online and ready. "
            f"Wake word and {hotkey_str} hotkey are active."
        )

        # Surface anything Eve queued from the phone while you were away.
        await self._announce_eve_handoffs()

        # 6. Main event loop — keeps process alive
        try:
            while self._running and not lifecycle.shutdown_requested():
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    async def stop(self):
        self._running = False
        self.vad.stop()
        self.trigger.stop()
        self.scheduler.stop()
        try:
            await mcp_manager.stop_all()
        except Exception:
            pass
        if self._ui_server:
            self._ui_server.stop()
        if self._eve_server:
            self._eve_server.stop()
        for proc_name, proc in [("island", self._island_proc), ("hud", self._hud_proc)]:
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except Exception:
                        proc.kill()
                except Exception as e:
                    logger.debug(f"[UI] error terminating {proc_name}: {e}")
        lifecycle.release_single_instance()
        logger.info("Jarvis shut down.")

    # ──────────────────────────────────────────────────────────────────
    # Trigger & speech event handlers
    # ──────────────────────────────────────────────────────────────────

    def _on_trigger_fired(self):
        """Called from trigger thread when wake word or hotkey fires."""
        if self.tts.is_speaking:
            logger.info("🛑 Hotkey pressed during speech — interrupting playback.")
            interrupted = self.tts.interrupted_text or self.tts.spoken_text
            if interrupted and not self._interrupted_summary:
                self._interrupted_summary = interrupted.strip()
            self.tts.interrupt()
            # Don't cancel a task that's waiting on the user's confirmation.
            if not self.consent.is_pending():
                self._cancel_llm.set()
                self.agent_loop.cancel()

        self._listening = True
        self._listening_timestamp = time.time()
        state_bridge.set("listening")
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
        if self.tts.is_speaking:
            interrupted = self.tts.interrupted_text or self.tts.spoken_text
            if interrupted and not self._interrupted_summary:
                self._interrupted_summary = interrupted.strip()
            self.tts.interrupt()
        self.arbiter.on_barge_in()
        # While a confirmation is pending, let the user's answer resolve it
        # instead of cancelling the task that's awaiting consent.
        if not self.consent.is_pending():
            self._cancel_llm.set()
            self.agent_loop.cancel()
        self._listening = True
        self._listening_timestamp = time.time()
        state_bridge.set("listening")

    async def _on_scheduler_speak(self, text: str):
        """Speak a scheduler reminder or queue it if audio is in use or a turn is actively processing."""
        if self._listening or self._is_processing_turn or self.tts.is_speaking:
            logger.info(f"⏰ Audio in use or turn in progress — queuing reminder: {text}")
            self._pending_reminders.append(text)
        else:
            await self._speak_async(text)

    async def _handle_screen_request(self) -> str:
        """Capture desktop screen and extract real active window, process, and OCR content."""
        try:
            from jarvis.tools.computer_use import _is_session_locked
            if _is_session_locked():
                return (
                    "[LIVE DESKTOP SCREEN CONTEXT]: The workstation is locked, so I cannot see the screen. "
                    f"Tell {self._user_name} to unlock it so you can look."
                )
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
            working_memory.set_screen_text(ocr_summary)

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
            self._is_processing_turn = True
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

            # ── Consent interception ──────────────────────────────────────
            # If a risky action is awaiting confirmation, treat this utterance
            # as the yes/no answer rather than a new command.
            if self.consent.is_pending():
                verdict = self.consent.interpret(text)
                if verdict is None:
                    await self._speak_async("Sorry, is that a yes or a no?")
                    self._arm_listening()
                    return
                self.consent.resolve(verdict)
                self.hud.clear_confirmation()
                self._arm_listening()
                return

            # ── 1. Fast-path intent check (< 1ms instant OS execution) ────
            fast_resp = await self.tool_router.try_fast_path(text)
            if fast_resp:
                logger.info(f"⚡ Fast-path action executed: {fast_resp}")
                fast_resp = self._weave_announcements(fast_resp)
                await self._speak_async(fast_resp)
                self._listening = True
                self._listening_timestamp = time.time()
                self._conversation_history.extend([
                    {"role": "user",      "content": text},
                    {"role": "assistant", "content": fast_resp},
                ])
                return

            # Check for screen / vision inspection command (exclude full screen, brightness, lock screen)
            lower_query = text.lower()
            is_screen_control = any(w in lower_query for w in ["full screen", "fullscreen", "lock screen", "brightness", "dim screen", "brighten"])
            if not is_screen_control and SCREEN_CAPTURE_PAT.search(lower_query):
                logger.info("📸 Screen inspection requested. Capturing desktop context...")
                screen_ctx = await self._handle_screen_request()
                text = f"{text}\n\n{screen_ctx}"

            # ── 1b. Deterministic slot clarification ─────────────────────
            # Ask instantly for a missing required value instead of letting the
            # weak model hallucinate one. Only fires on clearly-incomplete commands.
            clarify_q = missing_slot_question(text)
            if clarify_q:
                logger.info(f"❓ Missing slot → clarifying: {clarify_q}")
                await self._speak_async(clarify_q)
                self._arm_listening()
                self._conversation_history.extend([
                    {"role": "user",      "content": text},
                    {"role": "assistant", "content": clarify_q},
                ])
                return

            # ── 2. Mood analysis (zero-latency background update) ─────────
            mood_state = self.mood.current_mood
            # Apply the mood's delivery pace to the TTS engine for this turn.
            self.tts.speed_mult = mood_state.tts_speed
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
            working_memory.set_active_app(self._active_app)
            working_memory.start_task(text)
            state_bridge.set("thinking", text)

            system_prompt, user_msg = self.arbiter.build_prompt(
                new_user_input = text,
                user_name      = self._user_name,
                current_time   = datetime.datetime.now().strftime("%H:%M"),
                active_app     = self._active_app,
                mood           = mood_state.mood,
                tone_guidance  = mood_state.tone_guidance,
            )
            # Inject tiered-memory context: live state (L2) + related past (L3).
            system_prompt += self._build_memory_context(text)
            system_prompt += (
                "\nUse native function calls for actions, never read tool schemas aloud. "
                "Do not claim an action succeeded without a successful tool result. "
                "If the target, content, or required information is unclear, ask one concise "
                "clarifying question and wait. For example, ask for the topic before writing "
                "an unspecified essay. 'Your dashboard' means the Jarvis dashboard."
            )

            # ── 4. Semantic Intent Dispatcher (Tiered Hierarchy & Anti-Hallucination) ──
            intent_res = await intent_dispatcher.dispatch(text, active_app=self._active_app)
            logger.info(f"🎯 Intent Dispatcher: type={intent_res.intent_type}, source={intent_res.source}")

            final_response = ""
            if self._cancel_llm.is_set():
                final_response = ""
            elif intent_res.intent_type == "tool_call" and intent_res.tool_calls:
                # Direct tool calls (handles single and decomposed multi-intent)
                logger.info(f"🤖 Tool workflow via AgentLoop for: '{text}' ({len(intent_res.tool_calls)} calls)")
                final_response = await self.agent_loop.run(
                    user_request         = user_msg,
                    user_name            = self._user_name,
                    current_time         = datetime.datetime.now().strftime("%H:%M"),
                    active_app           = self._active_app,
                    mood                 = mood_state.mood,
                    conversation_history = self._conversation_history,
                    system_prompt        = system_prompt,
                    seed_tool_calls      = intent_res.tool_calls,
                    tools                = registry.get_tools_schema(),
                )
            elif intent_res.intent_type == "unsupported":
                # Honest communication — no faking or hallucinating success!
                final_response = intent_res.unsupported_reason
            elif intent_res.intent_type == "conversational" and intent_res.conversational_response:
                # Direct conversational response
                final_response = intent_res.conversational_response
            else:
                # Fallback to standard chat_with_tools / AgentLoop path
                self._cancel_llm.clear()
                messages = [{"role": "system", "content": system_prompt}]
                history = self._conversation_history[-self._max_history:]
                if history:
                    messages.extend(history)
                messages.append({"role": "user", "content": user_msg})

                tools, scoped = select_tools(text)
                logger.debug(f"🎯 Tool scope fallback: {scoped or ('none' if not tools else 'core')} ({len(tools)} tools)")

                use_cloud = self.cloud_llm is not None and allow_cloud(text, bool(tools))
                if use_cloud and self.cloud_llm is not None:
                    logger.info("☁️ Cloud model for this non-private turn.")
                    client = self.cloud_llm
                    cloud_messages = [{"role": "system", "content": CLOUD_CHAT_PROMPT},
                                      {"role": "user", "content": text}]
                    decision = await client.chat_with_tools(
                        messages     = cloud_messages,
                        tools        = [],
                        cancel_event = self._cancel_llm,
                        temperature  = mood_state.temperature,
                    )
                else:
                    decision = await self.llm.chat_with_tools(
                        messages     = messages,
                        tools        = tools,
                        cancel_event = self._cancel_llm,
                        temperature  = mood_state.temperature,
                    )

                if self._cancel_llm.is_set():
                    final_response = ""
                elif decision["tool_calls"] and tools:
                    logger.info(f"🤖 Tool workflow via AgentLoop for: '{text}'")
                    final_response = await self.agent_loop.run(
                        user_request         = user_msg,
                        user_name            = self._user_name,
                        current_time         = datetime.datetime.now().strftime("%H:%M"),
                        active_app           = self._active_app,
                        mood                 = mood_state.mood,
                        conversation_history = self._conversation_history,
                        system_prompt        = system_prompt,
                        seed_tool_calls      = decision["tool_calls"],
                        tools                = tools,
                    )
                else:
                    final_response = re.sub(r"[*#_`~]", "", decision["content"] or "").strip()
                    if not final_response:
                        final_response = "Sorry, I didn't quite get that, Sir."

            # Stitch any pending reminders or leftover context from interrupted turns
            final_response = self._weave_announcements(final_response)

            if final_response and not self._cancel_llm.is_set():
                logger.info(f"🤖 Jarvis: {final_response}")
                for sentence in re.split(r"(?<=[.!?])\s+", final_response):
                    if self._cancel_llm.is_set():
                        break
                    sentence = sentence.strip()
                    if sentence:
                        await asyncio.to_thread(self.tts.speak, sentence, False)

            # Keep listening open for 15 seconds for seamless conversational follow-ups
            self._listening = True
            self._listening_timestamp = time.time()
            logger.info("🎙️ Jarvis is standing by for follow-up questions (15s)...")

            # ── 5. Update conversation history ───────────────────────────
            if final_response:
                self._conversation_history.extend([
                    {"role": "user",      "content": text},
                    {"role": "assistant", "content": final_response},
                ])
                # Trim history to max window
                if len(self._conversation_history) > self._max_history:
                    self._conversation_history = \
                        self._conversation_history[-self._max_history:]

            # ── 6. Record this interaction in episodic memory (L3) ───────
            episodic_memory.record(
                user_input=text,
                tools_used=working_memory.recent_tools(),
                outcome=final_response,
                success=bool(final_response) and not self._cancel_llm.is_set(),
            )
            working_memory.clear_task()
            state_bridge.set("idle")

        except Exception as e:
            logger.exception(f"Pipeline error: {e}")
            await self._speak_async("I encountered an error. Please try again.")
        finally:
            self._is_processing_turn = False

    # ──────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────

    def _weave_announcements(self, response: str) -> str:
        """Weave pending background reminders or interrupted previous points into the spoken response."""
        prefix_parts = []
        if self._pending_reminders:
            reminders_str = "; ".join(self._pending_reminders)
            self._pending_reminders.clear()
            prefix_parts.append(f"A scheduled reminder: {reminders_str}")
        if self._interrupted_summary:
            leftover = self._interrupted_summary
            self._interrupted_summary = ""
            brief = leftover.split(".")[0].strip()
            if brief and len(brief) > 5:
                prefix_parts.append(f"Regarding what you asked earlier about {brief}")

        if prefix_parts and response:
            prefix = ". ".join(prefix_parts) + ". "
            return f"{prefix}{response}"
        return response

    async def _speak_async(self, text: str):
        """Speak text asynchronously without blocking the event loop."""
        await asyncio.to_thread(self.tts.speak, text)

    def _arm_listening(self):
        """Open the active listening window (used by the consent gate to await a reply)."""
        self._listening = True
        self._listening_timestamp = time.time()

    async def _start_mcp_servers(self):
        """Launch the MCP servers selected in config (best-effort, non-fatal)."""
        try:
            autostart = self._cfg.get("mcp", {}).get("autostart_servers", [])
            await mcp_manager.start_all(only=autostart)
        except Exception as e:
            logger.warning(f"[MCP] Startup notice: {e}")

    def _ui_port(self) -> int:
        return int(self._cfg.get("ui", {}).get("http_port", 8787))

    def _start_ui(self):
        """Start the control server and spawn the desktop orb (best-effort)."""
        ui_cfg = self._cfg.get("ui", {})
        if not ui_cfg.get("enabled", True):
            return
        try:
            self._ui_server = ControlServer(self._ui_port())
            self._ui_server.start()
        except Exception as e:
            logger.debug(f"[UI] server not started: {e}")
        # Clean up any leftover stale UI processes from earlier runs
        try:
            import psutil, os
            for p in psutil.process_iter(["pid", "cmdline"]):
                cmd = " ".join(p.info.get("cmdline") or [])
                if "jarvis.ui.island" in cmd or "jarvis.hud.window" in cmd:
                    if p.pid != os.getpid():
                        try:
                            p.terminate()
                        except Exception:
                            pass
        except Exception:
            pass

        if ui_cfg.get("launch_island", True):
            try:
                import subprocess, sys, os
                py = sys.executable
                pyw = py.replace("python.exe", "pythonw.exe")
                exe = pyw if Path(pyw).exists() else py
                flags = 0x08000000 if __import__("sys").platform == "win32" else 0
                self._island_proc = subprocess.Popen(
                    [exe, "-m", "jarvis.ui.island", f"--parent-pid={os.getpid()}"],
                    creationflags=flags,
                    cwd=str(Path.cwd()),
                )
            except Exception as e:
                logger.debug(f"[UI] island not launched: {e}")
        if ui_cfg.get("launch_hud", True):
            try:
                import subprocess, sys, os
                py = sys.executable
                pyw = py.replace("python.exe", "pythonw.exe")
                exe = pyw if Path(pyw).exists() else py
                flags = 0x08000000 if __import__("sys").platform == "win32" else 0
                self._hud_proc = subprocess.Popen(
                    [exe, "-m", "jarvis.hud.window", f"--parent-pid={os.getpid()}"],
                    creationflags=flags,
                    cwd=str(Path.cwd()),
                )
            except Exception as e:
                logger.debug(f"[HUD] window not launched: {e}")

    def _open_dashboard(self):
        """Open the dashboard in the default browser (from tray or voice)."""
        try:
            import webbrowser
            webbrowser.open(f"http://127.0.0.1:{self._ui_port()}/")
        except Exception as e:
            logger.debug(f"[UI] could not open dashboard: {e}")

    def _start_eve(self):
        """Start the Eve LAN sync server so the phone companion can connect."""
        eve_cfg = self._cfg.get("eve", {})
        if not eve_cfg.get("enabled", True):
            return
        try:
            from jarvis.eve.server import EveSyncServer
            self._eve_server = EveSyncServer(
                port=int(eve_cfg.get("port", 8765)),
                bind=eve_cfg.get("bind", "0.0.0.0"),
            )
            self._eve_server.start()
        except Exception as e:
            logger.debug(f"[Eve] sync server not started: {e}")

    async def _announce_eve_handoffs(self):
        """Speak any tasks/notes Eve queued from the phone, then acknowledge them."""
        try:
            from jarvis.memory.shared_bus import shared_bus
            items = shared_bus.pending(target="jarvis", limit=5)
            texts = [i["payload"].get("text", "") for i in items if i["payload"].get("text")]
            if texts:
                await self._speak_async(
                    f"While you were away, Eve noted: {'; '.join(texts)}."
                )
            for i in items:
                shared_bus.ack(i["id"])
        except Exception as e:
            logger.debug(f"Eve handoff announce skipped: {e}")

    async def _run_scheduled_command(self, text: str):
        """Execute a scheduled 'do' task through the agent loop and speak the result."""
        if not text or not text.strip() or self.tts.is_speaking:
            return
        try:
            logger.info(f"⏰ Running scheduled task: {text}")
            system_prompt, user_msg = self.arbiter.build_prompt(
                new_user_input = text,
                user_name      = self._user_name,
                current_time   = datetime.datetime.now().strftime("%H:%M"),
                active_app     = self._active_app,
                mood           = "neutral",
                tone_guidance  = "Be brief.",
            )
            self._cancel_llm.clear()
            final = await self.agent_loop.run(
                user_request  = user_msg,
                user_name     = self._user_name,
                current_time  = datetime.datetime.now().strftime("%H:%M"),
                active_app    = self._active_app,
                mood          = "neutral",
                system_prompt = system_prompt,
            )
            if final:
                await self._speak_async(final)
        except Exception as e:
            logger.warning(f"Scheduled task failed: {e}")

    def _build_memory_context(self, user_text: str) -> str:
        """Compose the live (L2) + related past (L3) memory block for the prompt."""
        parts = []
        live = working_memory.context_snapshot()
        if live:
            parts.append(f"\n\nLIVE CONTEXT:\n{live}")
        try:
            past = episodic_memory.search(user_text, limit=2)
        except Exception:
            past = []
        if past:
            lines = [
                f"- Earlier you asked '{e['user_input']}' and I used {', '.join(e['tools']) or 'no tools'}."
                for e in past
            ]
            parts.append("\n\nRELATED PAST ACTIONS:\n" + "\n".join(lines))
        return "".join(parts)

    def _time_of_day(self) -> str:
        hour = datetime.datetime.now().hour
        if hour < 12:  return "morning"
        if hour < 17:  return "afternoon"
        if hour < 21:  return "evening"
        return "night"
