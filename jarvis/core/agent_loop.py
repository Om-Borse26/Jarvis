"""
J.A.R.V.I.S. — ReAct Agent Loop (THE GAME CHANGER)
Implements the Plan → Execute → Observe → Decide → Repeat cycle.

This is the single most important architectural component. Without it,
Jarvis can only do single-step tasks. With it, Jarvis can handle ANY
multi-step operation by looping until the task is confirmed complete.

Pattern: ReAct (Reasoning + Acting)
  1. LLM receives: user request + available tools + observation history
  2. LLM decides: which tool to call (or FINAL_RESPONSE if done)
  3. Tool executes, result is recorded as an observation
  4. Loop back to step 1 with the new observation
  5. Repeat until LLM says FINAL_RESPONSE or MAX_ITERATIONS reached

Max iterations: 15 (prevents infinite loops)
"""
from __future__ import annotations

import re
import json
import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable
from loguru import logger

from jarvis.tools.registry import registry
from jarvis.core.rules_engine import rules_engine
from jarvis.security.consent import consent_manager
from jarvis.memory.working import working_memory


# ─── Data Structures ──────────────────────────────────────────────────────────

@dataclass
class Observation:
    """Records one step in the agent loop: what was done and what happened."""
    step: int
    reasoning: str       # Why the agent chose this action
    tool_name: str       # Which tool was called
    tool_args: Dict[str, Any]  # Arguments passed
    result: str          # What the tool returned
    timestamp: float = field(default_factory=time.time)

    def to_prompt_str(self) -> str:
        """Format this observation for injection into the LLM prompt."""
        args_str = ", ".join(f'{k}="{v}"' for k, v in self.tool_args.items())
        return (
            f"Step {self.step}:\n"
            f"  Reasoning: {self.reasoning}\n"
            f"  Action: {self.tool_name}({args_str})\n"
            f"  Result: {self.result}\n"
        )


@dataclass
class AgentDecision:
    """Parsed LLM output: either a tool call or a final response."""
    is_final: bool = False
    response_text: str = ""      # Only when is_final=True
    tool_name: str = ""          # Only when is_final=False
    tool_args: Dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""          # Why this decision was made


# ─── Agent Loop System Prompt ─────────────────────────────────────────────────

AGENT_SYSTEM_PROMPT = """You are Jarvis, {user_name}'s highly capable AI assistant with full control of their Windows PC.

CURRENT CONTEXT:
- Time: {time}
- Active application: {active_app}
- User mood: {mood}

AVAILABLE TOOLS:
{tools_schema}

EXECUTION RULES:
1. You can call ONE tool per step. After each tool call, you will see the result and can decide your next action.
2. Always think step-by-step. Break complex tasks into individual actions.
3. After each tool result, decide: is the task fully complete? If yes, give FINAL_RESPONSE. If no, call the next tool.
4. NEVER say you will do something — actually DO it by calling the tool.
5. For application interactions: check if the app is running first. If not, launch it before doing anything else.
6. For destructive actions (delete, kill): proceed but mention what you did.
7. If a tool fails, try an alternative approach before giving up.
8. Keep spoken responses natural and concise (1-2 sentences).

{observations_section}

RESPONSE FORMAT — you MUST use EXACTLY one of these two formats:

Format A (when you need to perform an action):
REASONING: <why you're taking this action>
TOOL_CALL: tool_name({{"param1": "value1", "param2": "value2"}})

Format B (when the task is fully complete):
FINAL_RESPONSE: <natural spoken response to the user>

CRITICAL: Use ONLY Format A or Format B. Never mix them. Never output free text without a prefix."""


def _build_observations_section(observations: List[Observation]) -> str:
    """Build the observation history section for the LLM prompt."""
    if not observations:
        return "PREVIOUS ACTIONS: None yet. This is your first step."
    
    lines = ["PREVIOUS ACTIONS (what you've done so far):"]
    for obs in observations:
        lines.append(obs.to_prompt_str())
    return "\n".join(lines)


# ─── Decision Parser ──────────────────────────────────────────────────────────

def parse_agent_decision(text: str) -> AgentDecision:
    """Parse the LLM output into a structured AgentDecision."""
    text = text.strip()

    # Check for FINAL_RESPONSE
    final_match = re.search(r"FINAL_RESPONSE:\s*(.+)", text, re.DOTALL)
    if final_match:
        response = final_match.group(1).strip()
        # Clean any markdown or formatting from spoken response
        response = re.sub(r"[*#_`~]", "", response).strip()
        return AgentDecision(is_final=True, response_text=response)

    # Check for TOOL_CALL (supports JSON, dict, and key=value args)
    tool_match = re.search(r"TOOL_CALL:\s*([a-zA-Z0-9_]+)\s*\((.*?)\)", text, re.DOTALL)
    if tool_match:
        tool_name = tool_match.group(1).strip()
        raw_args = tool_match.group(2).strip()

        # Parse reasoning if present
        reasoning = ""
        reason_match = re.search(r"REASONING:\s*(.+?)(?=TOOL_CALL:|$)", text, re.DOTALL)
        if reason_match:
            reasoning = reason_match.group(1).strip()

        # Parse tool arguments
        args = {}
        if raw_args:
            try:
                args = json.loads(raw_args)
            except Exception:
                try:
                    fixed = raw_args.replace("'", '"')
                    args = json.loads(fixed)
                except Exception:
                    try:
                        args = eval(f"dict({raw_args})")
                    except Exception:
                        kv_pairs = re.findall(r'([a-zA-Z0-9_]+)\s*=\s*(["\'])(.*?)\2', raw_args)
                        for k, _, v in kv_pairs:
                            args[k] = v

        return AgentDecision(
            is_final=False,
            tool_name=tool_name,
            tool_args=args,
            reasoning=reasoning,
        )

    # Fallback: if LLM just outputs natural text, treat it as final response
    # Strip common prefixes the LLM might add
    clean = re.sub(r"^(?:REASONING:.*?\n)?", "", text, flags=re.DOTALL).strip()
    if clean:
        clean = re.sub(r"[*#_`~]", "", clean).strip()
        return AgentDecision(is_final=True, response_text=clean)

    return AgentDecision(is_final=True, response_text="Task completed.")


# ─── The Agent Loop ───────────────────────────────────────────────────────────

class AgentLoop:
    """
    ReAct-style agentic loop that iteratively plans, executes, and observes
    until the task is complete or MAX_ITERATIONS is reached.
    """

    MAX_ITERATIONS = 15

    def __init__(self, llm_client, speak_fn: Optional[Callable] = None):
        """
        Args:
            llm_client: OllamaClient instance for LLM inference
            speak_fn: Optional async function to speak progress updates
        """
        self.llm = llm_client
        self.speak_fn = speak_fn
        self._cancel_event = asyncio.Event()

    async def run(
        self,
        user_request: str,
        user_name: str = "Sir",
        current_time: str = "",
        active_app: str = "Desktop",
        mood: str = "neutral",
        conversation_history: Optional[list] = None,
        system_prompt: Optional[str] = None,
        seed_tool_call: Optional[dict] = None,
    ) -> str:
        """
        Execute a user request through the iterative ReAct loop using native
        Ollama function-calling.

        Args:
            system_prompt: Optional caller-supplied system prompt (e.g. the steer-aware
                prompt from the Arbiter). Falls back to the built-in agent prompt.
            seed_tool_call: Optional first tool call already decided by the caller
                (e.g. the pipeline's initial tool-aware turn), so the loop does not
                re-query the model for step 1.

        Returns:
            The final spoken response text.
        """
        self._cancel_event.clear()
        observations: List[Observation] = []
        tools = registry.get_tools_schema()

        base_system = system_prompt or AGENT_SYSTEM_PROMPT.format(
            user_name=user_name,
            time=current_time,
            active_app=active_app,
            mood=mood,
            tools_schema="(provided via native function calling)",
            observations_section="",
        )

        messages: List[Dict[str, Any]] = [{"role": "system", "content": base_system}]
        if conversation_history:
            messages.extend(conversation_history[-6:])
        messages.append({"role": "user", "content": user_request})

        logger.info(f"🤖 Agent loop started for: '{user_request[:100]}'")

        pending_seed = seed_tool_call

        for iteration in range(1, self.MAX_ITERATIONS + 1):
            if self._cancel_event.is_set():
                logger.info("Agent loop cancelled by user.")
                return "Operation cancelled."

            # ── 1. Decide next action ────────────────────────────────────
            if pending_seed and iteration == 1:
                content = ""
                tool_calls = [pending_seed]
                pending_seed = None
            else:
                decision = await self.llm.chat_with_tools(
                    messages=messages,
                    tools=tools,
                    cancel_event=self._cancel_event,
                )
                content = decision["content"]
                tool_calls = decision["tool_calls"]

                # Fallback: model emitted the legacy "TOOL_CALL:" text format.
                if not tool_calls and content and "TOOL_CALL:" in content:
                    parsed = parse_agent_decision(content)
                    if not parsed.is_final and parsed.tool_name:
                        tool_calls = [{"name": parsed.tool_name, "arguments": parsed.tool_args}]
                        content = ""

            # ── 2. No tool call → final response ─────────────────────────
            if not tool_calls:
                final = re.sub(r"[*#_`~]", "", content or "").strip()
                if not final:
                    final = "Task completed." if observations else "I'm not sure how to help with that."
                logger.success(f"✅ Agent loop completed in {iteration} iteration(s): {final[:100]}")
                return final

            # ── 3. Execute the chosen tool (one per step) ────────────────
            tc = tool_calls[0]
            tool_name = tc.get("name", "")
            tool_args = tc.get("arguments", {}) or {}

            if not tool_name:
                return re.sub(r"[*#_`~]", "", content or "I've completed the requested action.").strip()

            from jarvis.security.audit import redact
            safe_args = redact(tool_args)
            logger.info(f"🔧 Agent step {iteration}/{self.MAX_ITERATIONS}: {tool_name}({safe_args})")

            # Consent gate: pause for spoken confirmation on high-risk actions.
            if consent_manager.requires_consent(tool_name, tool_args):
                approved = await consent_manager.confirm(tool_name, tool_args)
                if not approved:
                    logger.info(f"🛑 User declined '{tool_name}'. Aborting task.")
                    return "Understood, I won't proceed with that."

            # Speak a brief progress cue for genuinely multi-step tasks.
            if iteration >= 2 and self.speak_fn and iteration <= 5:
                asyncio.create_task(self.speak_fn("One moment."))

            try:
                exec_result = await registry.execute(tool_name, **tool_args)
                if exec_result.get("status") == "success":
                    result_text = exec_result.get("result", "Done.")
                else:
                    result_text = exec_result.get("message", "The tool reported an error.")
            except Exception as e:
                result_text = f"Error: {e}"
                logger.error(f"Tool {tool_name} failed: {e}")

            result_text = str(result_text)

            # ── 4. Record observation + feed result back to the model ────
            observations.append(Observation(
                step=iteration,
                reasoning=content,
                tool_name=tool_name,
                tool_args=tool_args,
                result=result_text[:1000],
            ))

            rules_engine.update_context(
                tool=tool_name,
                args=tool_args,
                result=result_text,
                entity=tool_args.get("path", tool_args.get("app_name", tool_args.get("file_path", ""))),
            )
            working_memory.add_observation(tool_name, tool_args, result_text)

            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [{"type": "function", "function": {"name": tool_name, "arguments": tool_args}}],
            })
            messages.append({
                "role": "tool",
                "content": result_text[:1000],
                "tool_name": tool_name,
            })

        # ── Max iterations reached ────────────────────────────────────────
        logger.warning(f"Agent loop hit MAX_ITERATIONS ({self.MAX_ITERATIONS})")
        summary_parts = [f"Step {o.step}: {o.tool_name} → {o.result[:50]}" for o in observations[-5:]]
        summary = "\n".join(summary_parts)
        return (
            f"I've completed {len(observations)} steps toward your request. "
            f"Here's what I accomplished:\n{summary}"
        )

    def cancel(self):
        """Cancel the running agent loop (e.g., on barge-in)."""
        self._cancel_event.set()
