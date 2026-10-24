"""
J.A.R.V.I.S. — Intelligent Tool Router & Fast-Path Dispatcher
Provides:
  1. Sub-millisecond direct intent matching for common Windows commands
     (Volume, media, launch app, kill app, lock, hardware metrics, desktop)
  2. Dynamic tool execution via the central ToolRegistry
  3. LLM tool-calling prompt augmentation and response parsing
"""
from __future__ import annotations

import re
import json
from typing import Optional, Tuple
from loguru import logger
from jarvis.tools.registry import registry


class ToolRouter:
    """Dispatches user intents directly or via LLM tool definitions."""

    def __init__(self) -> None:
        pass

    async def try_fast_path(self, utterance: str) -> Optional[str]:
        """
        Check if the user request matches a common deterministic system action.
        If matched, executes the tool instantly (< 1ms) and returns a spoken response.
        If not matched, returns None so it flows to the LLM.
        """
        text = utterance.lower().strip().rstrip(".!?")

        # ── Audio Controls ────────────────────────────────────────────────
        # "set volume to 50", "volume 75", "turn volume up to 80"
        vol_match = re.search(r"(?:set\s+)?volume(?:\s+to)?\s+(\d+)", text)
        if vol_match:
            val = int(vol_match.group(1))
            res = await registry.execute("set_volume", percent=val)
            return res.get("result", f"Volume set to {val} percent.")

        if text in ("mute", "mute audio", "mute volume", "mute the sound"):
            res = await registry.execute("mute_volume")
            return res.get("result", "Audio muted.")

        if text in ("unmute", "unmute audio", "unmute volume", "restore audio"):
            res = await registry.execute("unmute_volume")
            return res.get("result", "Audio unmuted.")

        if text in ("get volume", "what is the volume", "what's the volume", "check volume"):
            res = await registry.execute("get_volume")
            return res.get("result")

        # ── Media Controls ────────────────────────────────────────────────
        if text in ("pause", "pause music", "pause video", "play", "play music", "resume", "resume music"):
            res = await registry.execute("media_play_pause")
            return "Media playback toggled, Sir."

        if text in ("next track", "next song", "skip track", "skip song", "skip"):
            res = await registry.execute("media_next_track")
            return "Skipped to next track."

        if text in ("previous track", "previous song", "prev track", "prev song"):
            res = await registry.execute("media_prev_track")
            return "Returned to previous track."

        # ── Power & Desktop ───────────────────────────────────────────────
        if text in ("lock pc", "lock my pc", "lock computer", "lock workstation", "lock screen"):
            res = await registry.execute("lock_workstation")
            return res.get("result", "Workstation locked, Sir.")

        if text in ("sleep pc", "sleep computer", "put computer to sleep", "sleep"):
            res = await registry.execute("sleep_pc")
            return res.get("result", "Putting computer to sleep, Sir.")

        if text in ("show desktop", "minimize all", "minimize windows", "minimize all windows", "hide windows"):
            res = await registry.execute("show_desktop")
            return "Desktop displayed, Sir."

        # ── Hardware & Telemetry ──────────────────────────────────────────
        hardware_queries = [
            "gpu temp", "gpu temperature", "what is my gpu temp", "what's my gpu temp",
            "hardware status", "system metrics", "check hardware", "check battery",
            "check cpu", "check ram", "system status", "telemetry", "how is my pc doing"
        ]
        if any(hq in text for hq in hardware_queries):
            res = await registry.execute("get_hardware_metrics")
            return res.get("result")

        if text in ("what apps are running", "list apps", "running apps", "active apps", "list active apps"):
            res = await registry.execute("list_active_apps")
            return res.get("result")

        # ── YouTube & Web Searches ────────────────────────────────────────
        if text in ("open youtube", "open youtube in brave", "launch youtube", "go to youtube"):
            res = await registry.execute("open_website", url="https://www.youtube.com")
            return "Opening YouTube, Sir."

        yt_patterns = [
            r"(?:search\s+youtube\s+(?:for\s+)?)(.+)",
            r"(?:search\s+(?:for\s+)?)(.+?)(?:\s+on\s+youtube)",
            r"(?:open\s+(?:up\s+)?)(.+?)(?:\s+(?:on\s+youtube|videos))",
            r"(?:play\s+)(.+?)(?:\s+on\s+youtube)",
            r"(?:i\s+want(?:ed)?\s+to\s+see\s+(?:some\s+)?)(.+?)(?:\s+videos|\s+on\s+youtube)",
            r"(?:can\s+you\s+open\s+(?:up\s+)?)(.+?)(?:\s+videos|\s+on\s+youtube)",
            r"(?:show\s+(?:me\s+)?)(.+?)(?:\s+on\s+youtube|\s+videos)",
            r"^open\s+(?:up\s+)?(.+?)\s+videos$",
        ]
        for pattern in yt_patterns:
            m = re.search(pattern, text)
            if m:
                query = m.group(1).strip()
                query = re.sub(r"^(?:some|a|the)\s+", "", query).strip()
                if query:
                    search_q = f"{query} videos" if not query.endswith("videos") else query
                    res = await registry.execute("search_youtube", query=search_q)
                    return res.get("result", f"Opening {search_q} on YouTube, Sir.")

        web_patterns = [
            r"(?:search\s+(?:google|web|the\s+web)\s+(?:for\s+)?)(.+)",
            r"(?:search\s+(?:for\s+)?)(.+?)(?:\s+on\s+google|\s+on\s+the\s+web)",
            r"(?:google\s+)(.+)",
        ]
        for pattern in web_patterns:
            m = re.search(pattern, text)
            if m:
                query = m.group(1).strip()
                if query:
                    res = await registry.execute("search_web", query=query)
                    return res.get("result", f"Searching web for {query}, Sir.")

        # ── Process Launching & Killing ───────────────────────────────────
        # "open brave", "launch blender", "start discord", "open calculator"
        launch_match = re.match(r"^(?:open|launch|start)\s+([a-zA-Z0-9_\-\.\s]+)$", text)
        if launch_match:
            app_target = launch_match.group(1).strip()
            # Avoid matching general phrases like "open website" or "open file"
            if not app_target.startswith(("website", "url", "file", "folder", "directory", "youtube", "google")):
                res = await registry.execute("launch_application", app_name=app_target)
                return res.get("result", f"Opening {app_target}, Sir.")

        # "close brave", "kill chrome", "exit discord", "stop blender"
        kill_match = re.match(r"^(?:close|kill|terminate|exit|stop)\s+([a-zA-Z0-9_\-\.\s]+)$", text)
        if kill_match:
            app_target = kill_match.group(1).strip()
            if not app_target.startswith(("music", "video", "listening", "mode")):
                res = await registry.execute("kill_process", process_name=app_target)
                return res.get("result", f"Closed {app_target}, Sir.")

        # ── Clipboard & Network ───────────────────────────────────────────
        if text in ("read clipboard", "what's on my clipboard", "what is on my clipboard", "clipboard content"):
            res = await registry.execute("get_clipboard")
            return res.get("result")

        if text in ("what is my ip", "what's my ip", "check ip", "network info", "ip address"):
            res = await registry.execute("get_network_info")
            return res.get("result")

        return None

    def get_tool_prompt_section(self) -> str:
        """Return the formatted tool capabilities to inject into the LLM system prompt."""
        schema = registry.get_prompt_schema()
        return (
            "\n\n[WINDOWS PC AUTOMATION CAPABILITIES]\n"
            "You have full access to control this Windows PC using the following registered tools:\n"
            f"{schema}\n\n"
            "If the user asks you to perform an action requiring a tool, output ONLY a single tool call tag:\n"
            "TOOL_CALL: tool_name({\"param1\": \"value1\"})\n"
            "Jarvis will execute the tool and provide you the result immediately."
        )

    def parse_tool_call(self, text: str) -> Optional[Tuple[str, dict]]:
        """Parse TOOL_CALL: tool_name({...}) from LLM output."""
        match = re.search(r"TOOL_CALL:\s*([a-zA-Z0-9_]+)\s*\((.*?)\)", text, re.DOTALL)
        if match:
            tool_name = match.group(1)
            raw_args = match.group(2).strip()
            args = {}
            if raw_args:
                try:
                    args = json.loads(raw_args)
                except Exception:
                    # Attempt key=value fallback
                    try:
                        args = eval(f"dict({raw_args})")
                    except Exception:
                        logger.warning(f"Failed to parse tool call args: {raw_args}")
            return tool_name, args
        return None
