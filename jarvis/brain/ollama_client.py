"""
J.A.R.V.I.S. — Ollama LLM Client
Handles streaming inference from local Ollama models.
Supports model routing, tool call parsing, and async streaming.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import AsyncIterator, Optional

import ollama
from loguru import logger

from jarvis.core.config import load_config


class OllamaClient:
    """
    Async Ollama client with:
      - Model routing (fast / code / deep / long-context)
      - Token streaming with cancellation
      - Automatic retry on model load
      - Tool call detection from streamed output
    """

    def __init__(self):
        cfg                  = load_config()["llm"]
        self._host           = cfg["ollama_host"]
        self._fast_model     = cfg["fast_model"]
        self._code_model     = cfg["code_model"]
        self._deep_model     = cfg["deep_model"]
        self._long_ctx_model = cfg["long_ctx_model"]
        self._stream         = cfg["stream"]
        self._timeout        = cfg["timeout_seconds"]
        self._client         = ollama.AsyncClient(host=self._host)
        self._routing        = load_config()["llm"]["routing"]

    # ──────────────────────────────────────────────────────────────────
    # Model routing
    # ──────────────────────────────────────────────────────────────────

    def route_model(self, user_input: str, context_tokens: int = 0) -> str:
        """
        Choose the right local model for a given user input.

        Priority:
          1. Long context → long_ctx_model
          2. Code keywords → code_model
          3. Deep keywords → deep_model
          4. Default → fast_model (qwen3.5:4b — always in VRAM)
        """
        text_lower = user_input.lower()

        # Long-context check
        if context_tokens > self._routing["long_context_trigger"]:
            logger.debug(f"Model router → long-context ({context_tokens} tokens)")
            return self._long_ctx_model

        # Code path
        if any(kw in text_lower for kw in self._routing["code_keywords"]):
            logger.debug("Model router → code model")
            return self._code_model

        # Deep reasoning path
        if any(kw in text_lower for kw in self._routing["deep_keywords"]):
            logger.debug("Model router → deep model")
            return self._deep_model

        # Default fast path
        return self._fast_model

    # ──────────────────────────────────────────────────────────────────
    # Core inference
    # ──────────────────────────────────────────────────────────────────

    async def stream(
        self,
        system_prompt: str,
        user_message: str,
        model: Optional[str] = None,
        history: Optional[list] = None,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> AsyncIterator[str]:
        """
        Stream token-by-token LLM response.

        Yields:
            str: Individual text tokens as they arrive.

        Supports mid-stream cancellation via cancel_event.
        """
        if model is None:
            model = self.route_model(user_message)

        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        logger.debug(f"LLM stream → {model} | '{user_message[:80]}'")
        t0 = time.perf_counter()
        first_token = True

        VOICE_OPTIONS = {
            "num_ctx": 4096,
            "temperature": 0.6,
            "top_p": 0.9,
            "num_predict": 120,
        }

        try:
            in_think_block = False
            async for chunk in await self._client.chat(
                model      = model,
                messages   = messages,
                stream     = True,
                keep_alive = "24h",
                options    = VOICE_OPTIONS,
                think      = False,
            ):
                if cancel_event and cancel_event.is_set():
                    logger.debug("LLM stream cancelled.")
                    return

                token = chunk.get("message", {}).get("content", "")
                if not token:
                    continue

                # Filter out any stray thinking tags
                if "<think>" in token:
                    in_think_block = True
                    token = token.split("<think>")[0]
                if "</think>" in token:
                    in_think_block = False
                    token = token.split("</think>")[-1]
                if in_think_block or not token:
                    continue

                if first_token:
                    ttft = (time.perf_counter() - t0) * 1000
                    logger.debug(f"TTFT: {ttft:.0f}ms (model={model})")
                    first_token = False

                yield token

        except ollama.ResponseError as e:
            logger.error(f"Ollama error: {e}")
            yield f"I'm sorry, I encountered an error: {e}"

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        model: Optional[str] = None,
        history: Optional[list] = None,
    ) -> str:
        """Non-streaming completion — returns full response at once."""
        tokens = []
        async for token in self.stream(system_prompt, user_message, model, history):
            tokens.append(token)
        return "".join(tokens)

    # ──────────────────────────────────────────────────────────────────
    # Native function calling (ReAct agent loop)
    # ──────────────────────────────────────────────────────────────────

    async def chat_with_tools(
        self,
        messages: list,
        tools: list,
        model: Optional[str] = None,
        cancel_event: Optional[asyncio.Event] = None,
        temperature: float = 0.4,
        num_predict: int = 512,
        num_ctx: int = 4096,
    ) -> dict:
        """
        Single-shot chat using Ollama's native function-calling.

        Returns a normalized decision dict:
            {
              "content":    str,                     # spoken/final text (empty if tool call)
              "tool_calls": [{"name": str, "arguments": dict}, ...],
            }

        The caller (agent loop) inspects tool_calls: if present, execute them;
        otherwise treat `content` as the final response.
        """
        if model is None:
            last_user = next(
                (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"),
                "",
            )
            model = self.route_model(last_user)

        try:
            resp = await asyncio.wait_for(self._client.chat(
                model      = model,
                messages   = messages,
                tools      = tools or None,
                stream     = False,
                keep_alive = "24h",
                options    = {
                    "num_ctx": num_ctx,
                    "temperature": temperature,
                    "top_p": 0.9,
                    "num_predict": num_predict,
                },
                think      = False,
            ), timeout=self._timeout)
        except ollama.ResponseError as e:
            logger.error(f"Ollama tool-call error: {e}")
            return {"content": f"I encountered an error: {e}", "tool_calls": []}
        except Exception as e:
            logger.error(f"Ollama tool-call failure: {e}")
            return {"content": "I couldn't get a response from the local model in time. Please try again.", "tool_calls": []}

        if cancel_event and cancel_event.is_set():
            return {"content": "", "tool_calls": []}

        return self._normalize_tool_response(resp, parse_text_calls=bool(tools))

    @staticmethod
    def _normalize_tool_response(resp, parse_text_calls: bool = True) -> dict:
        """Flatten Ollama's response (pydantic object or dict) into a plain decision dict."""
        if isinstance(resp, dict):
            msg = resp.get("message", {}) or {}
        else:
            msg = getattr(resp, "message", None) or {}

        def _get(obj, key, default=None):
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)

        content = _get(msg, "content", "") or ""
        raw_calls = _get(msg, "tool_calls", None) or []

        tool_calls: list[dict] = []
        for tc in raw_calls:
            fn = _get(tc, "function", None)
            if fn is None:
                continue
            name = _get(fn, "name", "") or ""
            args = _get(fn, "arguments", {}) or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            if name:
                tool_calls.append({"name": name, "arguments": args})

        # Strip stray reasoning tags the model may leak into content.
        if content:
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

        if not parse_text_calls:
            return {"content": content, "tool_calls": []}

        if not tool_calls and content:
            candidate = content.strip()
            if candidate.startswith("<tool_call>"):
                candidate = re.sub(r"^<tool_call>\s*|\s*</tool_call>$", "", candidate).strip()
            if candidate.startswith("```"):
                candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate).strip()
            if candidate.startswith(("{", "[")):
                try:
                    payload = json.loads(candidate)
                    calls = payload if isinstance(payload, list) else payload.get("tool_calls", [payload])
                    for call in calls:
                        function = call.get("function", call)
                        name = function.get("name")
                        arguments = function.get("arguments", {})
                        if isinstance(arguments, str):
                            arguments = json.loads(arguments)
                        if not isinstance(name, str) or not name or not isinstance(arguments, dict):
                            raise ValueError("Invalid tool call")
                        tool_calls.append({"name": name, "arguments": arguments})
                    if not tool_calls:
                        raise ValueError("Empty tool calls")
                    content = ""
                except (ValueError, TypeError, AttributeError):
                    tool_calls = []
                    content = "I couldn't interpret that action safely. Please rephrase your request."

        return {"content": content, "tool_calls": tool_calls}

    async def warm_up(self):
        """
        Pre-load fast model into VRAM with exact 4096 context and runner settings.
        Prevents runner recreation delay on the first user query.
        """
        try:
            logger.info(f"Pre-warming LLM '{self._fast_model}' into VRAM with 4096 context...")
            t0 = time.perf_counter()
            # Stream 1 token through the exact same pipeline configuration
            async for _ in await self._client.chat(
                model      = self._fast_model,
                messages   = [
                    {"role": "system", "content": "You are Jarvis. Be concise."},
                    {"role": "user",   "content": "ping"}
                ],
                stream     = True,
                keep_alive = "24h",
                options    = {
                    "num_ctx": 4096,
                    "temperature": 0.6,
                    "top_p": 0.9,
                    "num_predict": 2,
                },
                think      = False,
            ):
                break
            elapsed = (time.perf_counter() - t0) * 1000
            logger.success(f"LLM '{self._fast_model}' warm, cached, and resident in VRAM ({elapsed:.0f}ms).")
        except Exception as e:
            logger.warning(f"LLM pre-warm notice: {e}")

    async def check_health(self) -> bool:
        """Check if Ollama server is reachable and fast model is available."""
        try:
            models_resp = await self._client.list()
            # Handle both pydantic object and dict responses
            if hasattr(models_resp, "models"):
                raw_list = models_resp.models
            elif isinstance(models_resp, dict):
                raw_list = models_resp.get("models", [])
            else:
                raw_list = []

            available = []
            for m in raw_list:
                if hasattr(m, "model"):
                    available.append(m.model)
                elif isinstance(m, dict):
                    available.append(m.get("model", ""))

            # Match model name with or without tag
            fast_base = self._fast_model.split(":")[0]
            matched = any(self._fast_model in m or fast_base in m for m in available)

            if not matched:
                logger.warning(
                    f"Fast model '{self._fast_model}' not found in Ollama. "
                    f"Available: {available}"
                )
                return False
            logger.success(f"Ollama healthy. Fast model '{self._fast_model}' ready.")
            return True
        except Exception as e:
            logger.error(f"Ollama unreachable: {e}")
            return False
