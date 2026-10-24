"""
J.A.R.V.I.S. — Ollama LLM Client
Handles streaming inference from local Ollama models.
Supports model routing, tool call parsing, and async streaming.
"""
from __future__ import annotations

import asyncio
import json
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

        try:
            in_think_block = False
            async for chunk in await self._client.chat(
                model    = model,
                messages = messages,
                stream   = True,
                options  = {"num_ctx": 4096},
                think    = False,
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

    async def check_health(self) -> bool:
        """Check if Ollama server is reachable and fast model is available."""
        try:
            models = await self._client.list()
            available = [m["model"] for m in models.get("models", [])]
            if self._fast_model not in available:
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
