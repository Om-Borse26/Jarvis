"""
J.A.R.V.I.S. — Interactive Consent Gate
Pauses high-risk actions (delete, shutdown, send message, run command, store/
delete credentials, …) until the user verbally confirms.

How it works across voice turns:
  1. A tool caller (agent loop or fast-path) calls `await consent_manager.confirm(...)`.
  2. The manager speaks a spoken prompt ("You're asking me to … Shall I proceed?"),
     arms the microphone, and awaits an asyncio.Future.
  3. The pipeline, on the NEXT utterance, sees `is_pending()` is True, interprets
     the words as yes/no, and calls `resolve()`.
  4. The awaiting caller wakes with True (proceed) or False (cancel/timeout).

The manager is a process-wide singleton so the pipeline, agent loop, and router
all coordinate through the same pending state.
"""
from __future__ import annotations

import asyncio
import re
from typing import Awaitable, Callable, Optional

from loguru import logger

from jarvis.security.audit import classify_risk

# Whole-word affirmatives / negatives.
_AFFIRM_WORDS = {
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "confirm", "confirmed",
    "proceed", "affirmative", "absolutely", "correct", "fine", "please",
}
_DENY_WORDS = {
    "no", "nope", "nah", "cancel", "stop", "abort", "negative", "don't",
    "cancel", "wait",
}
_AFFIRM_PHRASES = ("do it", "go ahead", "send it", "go for it", "please do", "carry on", "that's right")
_DENY_PHRASES = ("do not", "never mind", "nevermind", "hold on", "leave it", "forget it", "not now")

# Human-readable action descriptions for the spoken prompt.
_ACTION_PHRASES = {
    "delete_file": "permanently delete the file",
    "delete_directory": "delete the folder",
    "move_path": "move",
    "rename_path": "rename",
    "kill_process": "close",
    "shutdown_pc": "shut down the PC",
    "restart_pc": "restart the PC",
    "sleep_pc": "put the PC to sleep",
    "execute_shell": "run a system command",
    "execute_python": "run a Python script",
    "git_push": "push changes to the remote repository",
    "git_commit": "commit changes",
    "pip_install": "install a Python package",
    "npm_run": "run an npm script",
    "send_whatsapp_message": "send a WhatsApp message",
    "compose_email": "open an email to send",
    "save_secret": "store a credential",
    "delete_secret": "delete a stored credential",
    "automate_browser": "automate the browser",
}


class ConsentManager:
    """Singleton gate that requires spoken confirmation for high-risk actions."""

    def __init__(self, timeout: float = 30.0) -> None:
        self._pending: Optional[asyncio.Future] = None
        self._pending_desc: str = ""
        self.timeout = timeout
        # Set by the pipeline at startup.
        self.speak_fn: Optional[Callable[[str], Awaitable]] = None
        self.arm_fn: Optional[Callable[[], None]] = None
        self.hud_fn: Optional[Callable[[str], None]] = None   # show a visual confirmation card
        self.clear_hud_fn: Optional[Callable[[], None]] = None
        self._loop = None                                     # event loop for thread-safe resolve

    # ── State ─────────────────────────────────────────────────────────────────
    def is_pending(self) -> bool:
        return self._pending is not None and not self._pending.done()

    @property
    def pending_description(self) -> str:
        return self._pending_desc

    # ── Confirmation request (called by tool callers) ─────────────────────────
    async def confirm(self, tool_name: str, args: Optional[dict] = None) -> bool:
        """Require spoken confirmation. Returns True only on a clear 'yes'."""
        return await self.request(self.describe(tool_name, args or {}))

    async def request(self, description: str) -> bool:
        if self.is_pending():
            # Another confirmation is already in flight — deny to avoid races.
            logger.warning("[Consent] A confirmation is already pending; denying new request.")
            return False

        loop = asyncio.get_event_loop()
        self._loop = loop
        self._pending = loop.create_future()
        self._pending_desc = description
        logger.info(f"[Consent] Awaiting confirmation: {description}")

        prompt = f"{description} Shall I proceed?"
        if self.speak_fn:
            await self.speak_fn(prompt)
        if self.hud_fn:
            self.hud_fn(description)
        if self.arm_fn:
            self.arm_fn()

        try:
            approved = await asyncio.wait_for(self._pending, timeout=self.timeout)
        except asyncio.TimeoutError:
            approved = False
            logger.info("[Consent] Timed out with no answer — defaulting to no.")
            if self.speak_fn:
                await self.speak_fn("I didn't get a confirmation, so I'll hold off.")
        finally:
            self._pending = None
            self._pending_desc = ""
            if self.clear_hud_fn:
                self.clear_hud_fn()

        logger.info(f"[Consent] Decision: {'approved' if approved else 'declined'}.")
        return approved

    def resolve(self, approved: bool) -> None:
        """Called by the pipeline when the user's yes/no utterance arrives."""
        if self._pending and not self._pending.done():
            self._pending.set_result(approved)

    def resolve_threadsafe(self, approved: bool) -> None:
        """Resolve from another thread (e.g. a HUD button click via the HTTP server)."""
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self.resolve, approved)
        else:
            self.resolve(approved)

    def cancel(self) -> None:
        """Abort any pending confirmation (treated as a 'no')."""
        if self._pending and not self._pending.done():
            self._pending.set_result(False)

    # ── Helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def requires_consent(tool_name: str, args: Optional[dict] = None) -> bool:
        return classify_risk(tool_name, args) == "high"

    @staticmethod
    def describe(tool_name: str, args: dict) -> str:
        action = _ACTION_PHRASES.get(tool_name, tool_name.replace("_", " "))
        target = (
            args.get("path")
            or args.get("process_name")
            or args.get("app_name")
            or args.get("name")
            or args.get("command")
            or args.get("chat_name")
            or ""
        )
        target = str(target).strip()
        if target:
            return f"You're asking me to {action} '{target[:80]}'."
        return f"You're asking me to {action}."

    @staticmethod
    def interpret(text: str) -> Optional[bool]:
        """Classify an utterance as yes (True), no (False), or ambiguous (None)."""
        t = text.lower().strip().rstrip(".!?")
        words = set(re.findall(r"[a-z']+", t))

        if any(p in t for p in _DENY_PHRASES) or (words & _DENY_WORDS):
            return False
        if any(p in t for p in _AFFIRM_PHRASES) or (words & _AFFIRM_WORDS):
            return True
        return None


# Process-wide singleton
consent_manager = ConsentManager()
