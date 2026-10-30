"""
J.A.R.V.I.S. — Text simulation harness (testing only)

Runs typed commands through the SAME decision path the voice pipeline uses
(router fast-path → slot clarification → tool selection → model → agent loop),
but with the microphone/TTS removed and tools in DRY-RUN by default (recorded,
not executed), so nothing touches the real PC.

Usage:
  set JARVIS_LLM_PROVIDER=gemini   (or groq, or ollama)
  python -m scripts.simulate                 # run the built-in scenario list
  python -m scripts.simulate "open youtube"   # run one command
  python -m scripts.simulate --live ...        # actually execute tools (careful)

Each line prints: the path taken, tools offered, any tool calls, the spoken
reply, and latency.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import sys
import time
from pathlib import Path
from typing import List, Optional

# Allow running as a plain script (`python scripts/simulate.py`).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger

# Quieten the app's own INFO logs so the transcript is readable.
logger.remove()
logger.add(sys.stderr, level="WARNING")

import jarvis.tools  # noqa: F401  registers every tool
from jarvis.tools.registry import registry
from jarvis.tools.router import ToolRouter
from jarvis.core.clarify import missing_slot_question
from jarvis.core.intent_scope import select_tools, is_smalltalk
from jarvis.core.agent_loop import AgentLoop
from jarvis.brain.llm_provider import make_llm_client

SYSTEM_PROMPT = (
    "You are Jarvis, Om's calm, concise British AI assistant with control of a Windows PC. "
    "Use a tool ONLY when the user asks for an action you have a tool for. "
    "For greetings, opinions, or general questions, just reply in one or two short sentences — "
    "never call a tool. Never read tool names aloud. Address the user as 'Sir'."
)


class DryRunRegistry:
    """Wraps registry.execute to record calls instead of running them."""

    def __init__(self, live: bool):
        self.live = live
        self.calls: List[str] = []
        self._orig = registry.execute

    async def execute(self, tool_name: str, **kwargs):
        self.calls.append(f"{tool_name}({', '.join(f'{k}={v!r}' for k, v in kwargs.items())})")
        if self.live:
            return await self._orig(tool_name, **kwargs)
        tool = registry.get_tool(tool_name)
        if tool is None:
            return {"status": "error", "message": f"Tool '{tool_name}' not found in registry."}
        return {"status": "success", "result": f"[dry-run ok] {tool_name}"}


async def handle(text: str, llm, router: ToolRouter, live: bool) -> None:
    rec = DryRunRegistry(live)
    registry.execute = rec.execute  # type: ignore[assignment]
    t0 = time.perf_counter()
    path = ""
    reply = ""
    try:
        # 1. Deterministic fast path (router executes tools via rec).
        fast = await router.try_fast_path(text)
        if fast:
            path = "fast-path"
            reply = fast
        else:
            # 2. Missing-slot clarification.
            q = missing_slot_question(text)
            if q:
                path, reply = "clarify", q
            else:
                # 3. Tool selection + model decision.
                tools, scoped = select_tools(text)
                scope_label = "smalltalk/none" if not tools else (",".join(scoped) if scoped else "core")
                messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ]
                decision = await llm.chat_with_tools(messages=messages, tools=tools, temperature=0.3)
                if decision["tool_calls"] and tools:
                    path = f"model+agent [{scope_label}, {len(tools)} tools]"
                    loop = AgentLoop(llm)
                    reply = await loop.run(
                        user_request=text, user_name="Om",
                        current_time=datetime.datetime.now().strftime("%H:%M"),
                        system_prompt=SYSTEM_PROMPT,
                        seed_tool_calls=decision["tool_calls"], tools=tools,
                    )
                else:
                    path = f"model-chat [{scope_label}]"
                    reply = decision["content"] or "(no reply)"
    finally:
        registry.execute = rec._orig  # type: ignore[assignment]
    dt = (time.perf_counter() - t0) * 1000
    print(f"\n> {text}")
    print(f"  path   : {path}   ({dt:.0f} ms)")
    if rec.calls:
        print(f"  tools  : {' | '.join(rec.calls)}")
    print(f"  reply  : {reply}")


# A compact version of the handoff checklist (safe to run in dry-run).
SCENARIOS = [
    # small talk — must NOT call tools
    "how are you", "hello jarvis", "thank you", "tell me a joke", "who are you",
    # questions — answer, don't act
    "why is the sky blue", "what can you do",
    # focus / launch
    "switch to brave", "open vs code", "open notepad", "focus",
    # youtube phrasing
    "open youtube", "can you open youtube", "open youtube for me",
    # slot clarification
    "remind me to call mom", "search the web", "write an essay", "send a whatsapp message",
    # system commands
    "set volume to 30", "what time is it", "what apps are running",
    # compound
    "open brave and set volume to 20",
    # knowledge (uses Tavily if key present)
    "what is the capital of France",
    # the two that misbehaved before
    "open youtube and play lofi", "how are you doing today",
]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("commands", nargs="*", help="Commands to run (default: scenario list).")
    ap.add_argument("--live", action="store_true", help="Actually execute tools (DANGER).")
    args = ap.parse_args()

    llm = make_llm_client()
    router = ToolRouter()
    provider = type(llm).__name__
    model = getattr(llm, "_fast_model", "?")
    print(f"=== Jarvis simulation | client={provider} model={model} | "
          f"{'LIVE' if args.live else 'DRY-RUN'} ===")

    cmds = args.commands or SCENARIOS
    for c in cmds:
        try:
            await handle(c, llm, router, args.live)
        except Exception as e:
            print(f"\n> {c}\n  ERROR: {e!r}")


if __name__ == "__main__":
    asyncio.run(main())
