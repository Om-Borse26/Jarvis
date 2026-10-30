"""
J.A.R.V.I.S. — Semantic Query Reformatter & Intent Dispatcher
Dedicated semantic intent reformatter and matcher using Gemini (with fallback to local Ollama).

Responsibilities:
  1. Disambiguate and reformat natural queries into canonical tool calls without requiring exact keywords.
  2. Decompose compound multi-intent requests (e.g. "increase master volume to 90% and turn down brightness to 50%").
  3. Resolve implicit application context ("create a file in it", "here").
  4. Anti-Hallucination & Anti-Force Matching: Never fake tool execution or forcibly match an unrelated query.
  5. "Try Before Giving Up" execution hierarchy:
     - Tier 1: Direct native tool execution.
     - Tier 2: Built-in app shortcut lookup via RulesEngine.
     - Tier 3: Live Tavily web search for Windows keyboard shortcut.
     - Tier 4: Honest explanation that a custom tool needs to be created.
"""
from __future__ import annotations

import os
import re
import json
import asyncio
import urllib.request
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
from loguru import logger

from jarvis.core.env import load_env_file
from jarvis.tools.registry import registry
from jarvis.core.rules_engine import rules_engine, APP_SHORTCUTS
from jarvis.tools.knowledge import _tavily_answer


@dataclass
class IntentResult:
    """Output of semantic intent reformatter & matcher."""
    intent_type: str                     # "tool_call", "app_action", "conversational", "unsupported"
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    app_action: Optional[Dict[str, str]] = None  # {"app": ..., "action": ..., "description": ...}
    conversational_response: str = ""
    unsupported_reason: str = ""
    source: str = "direct"               # "gemini_intent", "gemini_primary", "ollama", "shortcut_tier"


REFORMATTER_SYSTEM_PROMPT = """You are the Semantic Query Reformatter and Intent Matcher for J.A.R.V.I.S. (Windows AI Assistant).
Your job is to analyze the user's spoken query and produce a structured, canonical execution plan.

CONTEXT:
- Active foreground window/application: {active_app}
- Available tool names and descriptions:
{tools_summary}

CRITICAL RULES:
1. DECOMPOSE MULTI-INTENT: If user asks for multiple actions in one sentence (e.g. "increase master volume to 90% and turn down brightness to 50%"), emit MULTIPLE tool calls in sequential order.
2. CONTEXTUAL RESOLUTION: If user says "create a file in it", "here", "this directory", map to `create_file` (with directory="" or appropriate path relative to active workspace).
3. ANTI-HALLUCINATION / ANTI-FORCE MATCHING:
   - If the utterance is smalltalk, greeting, or conversational chat, output "conversational" with a polite response.
   - NEVER forcibly match an action to an unrelated tool (e.g., do not map cooking or hardware actions to file tools).
   - If the user wants to perform an action inside an active app (e.g. "format this document", "new file in vscode", "split view in blender", "zoom in") and NO direct native tool exists, set intent_type to "app_action" specifying "app" and "action".
   - If an action cannot be satisfied by any tool or application shortcut, set intent_type to "unsupported" with a concise explanation.

RESPONSE FORMAT (JSON ONLY, NO MARKDOWN, NO CODEBLOCKS):
{{
  "intent_type": "tool_call" | "app_action" | "conversational" | "unsupported",
  "tool_calls": [
    {{"name": "tool_name", "arguments": {{"param1": "val1"}}}}
  ],
  "app_action": {{
    "app": "vscode",
    "action": "format document",
    "description": "format active code file"
  }},
  "conversational_response": "Short natural response if conversational",
  "unsupported_reason": "Clear reason if unsupported"
}}
"""


class IntentDispatcher:
    """Dispatches user queries through semantic reformatting, tool matching, and shortcut fallbacks."""

    def __init__(self):
        load_env_file()
        self._intent_api_key = os.environ.get("GEMINI_INTENT_API_KEY", "").strip()
        self._primary_api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        self._gemini_url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
        self._model = "gemini-flash-lite-latest"
        self._timeout = 7.0

    def _get_api_key(self) -> Optional[Tuple[str, str]]:
        """Return (key, source_name) or None."""
        load_env_file()
        k = os.environ.get("GEMINI_INTENT_API_KEY", "").strip()
        if k:
            return k, "gemini_intent"
        k2 = os.environ.get("GEMINI_API_KEY", "").strip()
        if k2:
            return k2, "gemini_primary"
        return None

    def _call_gemini_json(self, system_prompt: str, user_query: str) -> Optional[dict]:
        """Synchronous HTTP call to Gemini OpenAI-compatible JSON endpoint."""
        key_info = self._get_api_key()
        if not key_info:
            return None
        api_key, _ = key_info

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
            "max_tokens": 512,
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._gemini_url,
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "Jarvis-IntentDispatcher/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                content = data["choices"][0]["message"]["content"]
                return json.loads(content)
        except Exception as e:
            logger.warning(f"[IntentDispatcher] Gemini cloud call notice: {e}")
            return None

    async def _call_reformatter(self, user_query: str, active_app: str = "Desktop") -> Optional[dict]:
        """Execute semantic reformatting call in background thread with local Ollama fallback."""
        import inspect
        tools_summary = []
        for tool in registry.list_tools():
            desc = tool.description or ""
            try:
                sig = inspect.signature(tool.func)
                param_names = [p.name for p in sig.parameters.values() if p.name not in ("args", "kwargs")]
                params_str = f"({', '.join(param_names)})"
            except Exception:
                params_str = "()"
            tools_summary.append(f"- {tool.name}{params_str}: {desc[:100]}")
        summary_text = "\n".join(tools_summary)

        system_prompt = REFORMATTER_SYSTEM_PROMPT.format(
            active_app=active_app,
            tools_summary=summary_text,
        )

        # 1. Try Gemini cloud first (< 1s, high quality)
        res = await asyncio.to_thread(self._call_gemini_json, system_prompt, user_query)
        if res and isinstance(res, dict):
            return res

        # 2. Fallback to local Ollama fast model if cloud is offline
        try:
            from jarvis.brain.ollama_client import OllamaClient
            ollama = OllamaClient()
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query},
            ]
            reply = await ollama.chat_with_tools(messages=messages, tools=[], temperature=0.1)
            raw = reply.get("content", "")
            # Extract JSON block
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                return json.loads(m.group(0))
        except Exception as e:
            logger.warning(f"[IntentDispatcher] Local Ollama fallback notice: {e}")

        return None

    def _parse_hotkey_from_text(self, text: str) -> Optional[str]:
        """Extract hotkey string like 'ctrl+shift+f' or 'shift+alt+f' from natural text."""
        # Find combinations of keys joined by + or commas
        pat = r"\b(?:ctrl|control|alt|shift|win|windows|cmd|tab|enter|esc|space|[a-z0-9]|f[1-9]|f1[0-2])(?:\s*\+\s*(?:ctrl|control|alt|shift|win|windows|cmd|tab|enter|esc|space|[a-z0-9]|f[1-9]|f1[0-2]))+\b"
        matches = re.findall(pat, text, re.IGNORECASE)
        if matches:
            # Pick longest match
            best = max(matches, key=len)
            parts = [p.strip().lower() for p in best.split("+")]
            # Standardize names
            norm_parts = []
            for p in parts:
                if p in ("control", "ctl"):
                    norm_parts.append("ctrl")
                elif p in ("windows", "win"):
                    norm_parts.append("win")
                elif p in ("escape",):
                    norm_parts.append("esc")
                else:
                    norm_parts.append(p)
            return "+".join(norm_parts)
        return None

    async def _resolve_app_action(self, app: str, action: str) -> IntentResult:
        """
        Implements 'Try Before Giving Up' hierarchy:
        Tier 2: Built-in app shortcut
        Tier 3: Live Tavily search for Windows shortcut
        Tier 4: Honest explanation that custom tool needs to be created
        """
        app_clean = (app or "general").strip().lower()
        act_clean = (action or "").strip().lower()

        # Tier 2: Check built-in rules engine shortcuts
        shortcut = rules_engine.get_app_shortcut(app_clean, act_clean)
        if shortcut:
            hotkey_str = "+".join(shortcut)
            logger.info(f"[IntentDispatcher] Tier 2: Found built-in shortcut for '{action}' in {app}: {hotkey_str}")
            return IntentResult(
                intent_type="tool_call",
                tool_calls=[{"name": "keyboard_hotkey", "arguments": {"hotkey": hotkey_str}}],
                source="rules_engine_shortcut",
            )

        # Tier 3: Live Tavily search for Windows keyboard shortcut
        logger.info(f"[IntentDispatcher] Tier 3: Querying Tavily for keyboard shortcut '{action}' in '{app}'...")
        tavily_q = f"keyboard shortcut for {act_clean} in {app_clean} Windows"
        search_answer = await asyncio.to_thread(_tavily_answer, tavily_q)
        if search_answer:
            parsed_hotkey = self._parse_hotkey_from_text(search_answer)
            if parsed_hotkey:
                logger.info(f"[IntentDispatcher] Tier 3: Tavily resolved shortcut: {parsed_hotkey} (from: {search_answer[:80]})")
                # Dynamically cache in rules_engine for future calls
                cat = "vscode" if "code" in app_clean else ("browser" if any(b in app_clean for b in ["brave", "chrome", "edge"]) else "general")
                if cat in APP_SHORTCUTS:
                    APP_SHORTCUTS[cat][act_clean] = parsed_hotkey.split("+")

                return IntentResult(
                    intent_type="tool_call",
                    tool_calls=[{"name": "keyboard_hotkey", "arguments": {"hotkey": parsed_hotkey}}],
                    source="tavily_shortcut_search",
                )

        # Tier 4: Honest explanation
        logger.warning(f"[IntentDispatcher] Tier 4: No tool or shortcut available for '{action}' in {app}.")
        explanation = (
            f"I couldn't find a direct keyboard shortcut or built-in tool for '{action}' in {app}, Sir. "
            f"A custom tool would need to be created for this functionality."
        )
        return IntentResult(
            intent_type="unsupported",
            unsupported_reason=explanation,
            source="hierarchy_exhausted",
        )

    async def dispatch(self, user_query: str, active_app: str = "Desktop") -> IntentResult:
        """
        Main entry point: Reformats query and matches against tools/hierarchy.
        """
        raw = await self._call_reformatter(user_query, active_app)
        if not raw:
            # Fallback when model is completely unreachable
            return IntentResult(
                intent_type="unsupported",
                unsupported_reason="I couldn't resolve the intent for your request right now, Sir.",
                source="fallback",
            )

        intent_type = raw.get("intent_type", "conversational")

        # 1. Direct tool calls (handles single and multi-intent)
        if intent_type == "tool_call":
            calls = raw.get("tool_calls", [])
            valid_calls = []
            for c in calls:
                name = c.get("name")
                args = c.get("arguments", {})
                if name and registry.get_tool(name):
                    valid_calls.append({"name": name, "arguments": args})
            if valid_calls:
                return IntentResult(
                    intent_type="tool_call",
                    tool_calls=valid_calls,
                    source="reformatter_tool_call",
                )

        # 2. Application action request without native tool -> Hierarchy
        if intent_type == "app_action" or (intent_type == "tool_call" and not raw.get("tool_calls")):
            app_act = raw.get("app_action") or {}
            app_name = app_act.get("app") or active_app
            action_name = app_act.get("action") or user_query
            return await self._resolve_app_action(app_name, action_name)

        # 3. Unsupported intent -> Honest communication
        if intent_type == "unsupported":
            reason = raw.get("unsupported_reason") or f"I don't have a way to do that yet, Sir."
            return IntentResult(
                intent_type="unsupported",
                unsupported_reason=reason,
                source="reformatter_unsupported",
            )

        # 4. Conversational
        resp = raw.get("conversational_response") or "At your service, Sir."
        return IntentResult(
            intent_type="conversational",
            conversational_response=resp,
            source="reformatter_conversational",
        )


# Global singleton
intent_dispatcher = IntentDispatcher()
