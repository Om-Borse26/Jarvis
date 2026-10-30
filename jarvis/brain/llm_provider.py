"""
J.A.R.V.I.S. — Pluggable LLM provider

Lets the pipeline run against a cloud model (Groq or Gemini) that is API-compatible
with OpenAI chat-completions, as a stand-in for local Ollama during testing on
machines that can't host the local models.

Selection (no code change needed):
  • env JARVIS_LLM_PROVIDER = ollama | groq | gemini   (default: ollama)
  • env JARVIS_LLM_MODEL    = override the model name

Both Groq and Gemini accept the exact OpenAI-format tool schemas that
`registry.get_tools_schema()` already produces, so no schema translation is needed.
The client exposes the same surface the pipeline/agent-loop use on OllamaClient:
`chat_with_tools`, `stream`, `warm_up`, `check_health`, `route_model`, `_fast_model`.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import urllib.request
from typing import AsyncIterator, Optional

from loguru import logger

from jarvis.core.config import load_config
from jarvis.core.env import load_env_file

_PRESETS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
        "default_model": "openai/gpt-oss-20b",
        "extra": {},
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_env": "GEMINI_API_KEY",
        "default_model": "gemini-flash-lite-latest",
        "extra": {},
    },
}


def make_llm_client():
    """Return the LLM client selected by env/config (default: local Ollama)."""
    load_env_file()
    provider = (os.environ.get("JARVIS_LLM_PROVIDER")
                or load_config().get("llm", {}).get("provider")
                or "ollama").lower().strip()
    if provider in _PRESETS:
        logger.info(f"[LLM] Using cloud provider '{provider}'.")
        return OpenAICompatClient(provider)
    from jarvis.brain.ollama_client import OllamaClient
    return OllamaClient()


class OpenAICompatClient:
    """Minimal async client for any OpenAI chat-completions compatible endpoint."""

    def __init__(self, provider: str, model: Optional[str] = None) -> None:
        load_env_file()
        preset = _PRESETS[provider]
        self.provider = provider
        self._base_url = preset["base_url"].rstrip("/")
        self._api_key = os.environ.get(preset["key_env"], "").strip()
        self._fast_model = (model or os.environ.get("JARVIS_LLM_MODEL")
                            or preset["default_model"])
        self._extra = preset.get("extra", {})
        self._timeout = max(60, int(load_config().get("llm", {}).get("timeout_seconds", 30)))
        if not self._api_key:
            logger.warning(f"[LLM] {preset['key_env']} is not set — {provider} calls will fail.")

    # The pipeline routes by returning a model name; one cloud model covers all.
    def route_model(self, user_input: str, context_tokens: int = 0) -> str:
        return self._fast_model

    async def warm_up(self) -> None:
        return None

    async def check_health(self) -> bool:
        return bool(self._api_key)

    # ── OpenAI message sanitation ─────────────────────────────────────────
    @staticmethod
    def _sanitize(messages: list) -> list:
        """
        Convert the pipeline/agent-loop message history into clean OpenAI roles.
        Ollama-style assistant tool_calls and 'tool' role messages (which carry no
        tool_call_id) are flattened into plain text so the endpoint never 400s.
        """
        out = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "") or ""
            if role == "tool":
                name = m.get("tool_name", "tool")
                out.append({"role": "user", "content": f"[result of {name}] {content}"})
            elif role == "assistant" and m.get("tool_calls"):
                calls = ", ".join(
                    tc.get("function", {}).get("name", "") for tc in m["tool_calls"]
                )
                out.append({"role": "assistant", "content": content or f"(calling {calls})"})
            else:
                out.append({"role": role, "content": content})
        return out

    def _post(self, payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self._base_url}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Jarvis/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    async def chat_with_tools(
        self,
        messages: list,
        tools: list,
        model: Optional[str] = None,
        cancel_event=None,
        temperature: float = 0.4,
        num_predict: int = 512,
        num_ctx: int = 4096,
    ) -> dict:
        payload = {
            "model": model or self._fast_model,
            "messages": self._sanitize(messages),
            "temperature": temperature,
            "max_tokens": num_predict,
            **self._extra,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        try:
            data = await asyncio.wait_for(asyncio.to_thread(self._post, payload),
                                          timeout=self._timeout + 5)
        except Exception as e:
            logger.error(f"[LLM] {self.provider} call failed: {e}")
            return {"content": "I couldn't reach the language model just now, Sir.", "tool_calls": []}
        if cancel_event is not None and cancel_event.is_set():
            return {"content": "", "tool_calls": []}
        return self._normalize(data)

    @staticmethod
    def _normalize(data: dict) -> dict:
        try:
            msg = data["choices"][0]["message"]
        except Exception:
            return {"content": "", "tool_calls": []}
        content = (msg.get("content") or "").strip()
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {}) or {}
            name = fn.get("name", "")
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args or "{}")
                except Exception:
                    args = {}
            if name:
                calls.append({"name": name, "arguments": args if isinstance(args, dict) else {}})
        return {"content": content, "tool_calls": calls}

    async def stream(self, system_prompt: str, user_message: str, model=None,
                     history=None, cancel_event=None) -> AsyncIterator[str]:
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})
        res = await self.chat_with_tools(messages, tools=[], model=model,
                                         cancel_event=cancel_event)
        yield res["content"]
