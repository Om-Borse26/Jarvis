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


from jarvis.audio.accent_normalizer import SpeechNormalizer
from jarvis.security.consent import consent_manager


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
        norm_text = SpeechNormalizer.normalize(utterance)
        text = re.sub(r"\s+", " ", norm_text.lower().strip().rstrip(".!?"))
        clean_cmd = re.sub(r"\s+", " ", SpeechNormalizer.clean_command(text).lower())

        if re.match(r"^(?:did|have|has|was|were)\s", text):
            return None
        youtube = re.fullmatch(
            r"(?:can you |could you |please )?open youtube and search(?: for)? (?:some )?(.+)", text
        )
        if youtube:
            result = await registry.execute("search_youtube", query=youtube.group(1))
            return result.get("result", result.get("message"))
        if re.search(r"\b(?:and|then|also)\b", text):
            return None
        instant = {
            "open dashboard": "open_dashboard", "open the dashboard": "open_dashboard",
            "bring up the dashboard": "open_dashboard", "bring up your dashboard": "open_dashboard",
            "turn yourself off": "stop_jarvis", "shut yourself down": "stop_jarvis",
            "list mcp servers": "list_mcp_servers", "list the mcp servers": "list_mcp_servers",
            "come forward": "island_come_forward", "come ahead": "island_come_forward",
            "focus on yourself": "island_come_forward", "show yourself": "island_come_forward",
            "step back": "island_send_back", "step aside": "island_send_back",
            "minimize yourself": "island_send_back", "go to the background": "island_send_back",
        }
        command = re.sub(r"^(?:can you |could you |please )", "", text)
        if command in instant:
            result = await registry.execute(instant[command])
            return result.get("result", result.get("message"))

        # ── Run a saved routine/procedure ─────────────────────────────────
        # "run my work routine", "start my morning routine", "do my gaming setup"
        proc_m = re.match(
            r"^(?:can you |could you |please )?(?:run|start|do|execute|launch)\s+(?:my |the )?(.+?)(?:\s+routine|\s+procedure|\s+recipe|\s+macro|\s+setup)\s*$",
            text,
        )
        if proc_m:
            name = proc_m.group(1).strip()
            if name:
                res = await registry.execute("run_procedure", name=name)
                return res.get("result", res.get("message"))

        # ── Audio & Volume Controls ───────────────────────────────────────
        # 1. Absolute volume: "laptop's volume to 90%", "turn volume up to 90", "volume 80"
        vol_match = re.search(r"(?:volume|sound|audio|laptop.*?volume).*?(\d{1,3})\s*(?:%|percent)?", text)
        if not vol_match:
            vol_match = re.search(r"(?:increase|decrease|turn|make|set|put).*?(?:to|at)\s+(\d{1,3})\s*(?:%|percent)?", text)
        if vol_match:
            val = int(vol_match.group(1))
            if 0 <= val <= 100:
                res = await registry.execute("set_volume", percent=val)
                return res.get("result", f"Master volume set to {val} percent, Sir.")

        # 2. Relative volume: "can you decrease the system volume", "increase volume", "make it louder"
        if re.search(r"(?:increase|turn\s+up|raise|boost|make|crank)\s+(?:the\s+)?(?:system\s+|laptop\s+|master\s+)?(?:volume|sound|audio)", text) or any(k in text or k in clean_cmd for k in (
            "increase the volume", "increase volume", "turn up volume", "turn up the volume",
            "volume up", "louder", "make it louder", "make volume louder"
        )):
            res = await registry.execute("change_volume_relative", delta_percent=10)
            return res.get("result", "Volume increased by 10 percent, Sir.")

        if re.search(r"(?:decrease|turn\s+down|lower|reduce)\s+(?:the\s+)?(?:system\s+|laptop\s+|master\s+)?(?:volume|sound|audio)", text) or any(k in text or k in clean_cmd for k in (
            "decrease the volume", "decrease volume", "turn down volume", "turn down the volume",
            "volume down", "quieter", "make it quieter", "lower the volume", "lower volume"
        )):
            res = await registry.execute("change_volume_relative", delta_percent=-10)
            return res.get("result", "Volume decreased by 10 percent, Sir.")

        if text in ("mute", "mute audio", "mute volume", "mute the sound"):
            res = await registry.execute("mute_volume")
            return res.get("result", "Audio muted.")

        if text in ("unmute", "unmute audio", "unmute volume", "restore audio"):
            res = await registry.execute("unmute_volume")
            return res.get("result", "Audio unmuted.")

        if text in ("get volume", "what is the volume", "what's the volume", "check volume"):
            res = await registry.execute("get_volume")
            return res.get("result")

        # ── Active Application & Workspace Context ────────────────────────
        active_app_queries = [
            "which application am i in", "in which application i am currently",
            "which application i am currently", "in which application am i",
            "what app am i using", "what window is active", "what application is open",
            "what application is currently open", "where am i", "current app", "active app"
        ]
        if any(aq in text for aq in active_app_queries):
            res = await registry.execute("get_current_active_window")
            return res.get("result")

        # ── Email / Mail Composition ──────────────────────────────────────
        # "compose a mail", "compose a male", "send an email", "write a mail"
        email_queries = [
            "compose a mail", "compose mail", "compose an email", "compose email",
            "send a mail", "send an email", "write a mail", "write an email",
            "open email", "new email", "new mail"
        ]
        if any(eq in text or eq in clean_cmd for eq in email_queries):
            res = await registry.execute("compose_email")
            return res.get("result", "Opening your email composer, Sir.")

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

        # ── Filesystem & Explorer Controls ────────────────────────────────
        # 0. Compound command: "open vs code and create a demo folder in it"
        comp_match = re.search(r"(?:open|launch)\s+([a-zA-Z0-9_\-\s]+?)\s+and\s+(?:create|make)\s+(?:a\s+)?(?:dummy\s+)?([a-zA-Z0-9_\-]+)?\s*(?:folder|directory)(?:\s+(?:called|named)\s+([a-zA-Z0-9_\-]+))?", clean_cmd)
        if comp_match:
            app_target = comp_match.group(1).strip()
            folder_name = comp_match.group(2) or comp_match.group(3) or "demo_folder"
            is_vscode = any(v in app_target.lower() for v in ["code", "vscode", "vs code"])
            if is_vscode:
                res = await registry.execute("create_directory", path=folder_name, in_vscode=True)
                return res.get("result", f"Created folder '{folder_name}' and opened it in VS Code, Sir.")
            else:
                await registry.execute("launch_application", app_name=app_target)
                res = await registry.execute("create_directory", path=folder_name)
                return f"Switched to {app_target} and {res.get('result', f'created folder {folder_name}')}"

        # 1. Targeted folder creation: "create a dummy folder in the root directory of vs code that I have opened", "create a dummy folder in vs code"
        target_f = re.search(r"(?:create|make)\s+(?:a\s+)?(?:dummy\s+)?([a-zA-Z0-9_\-]+)?\s*(?:folder|directory)(?:\s+(?:called|named)\s+([a-zA-Z0-9_\-]+))?\s*(?:in|inside)\s*(?:the\s+root\s+directory\s+of\s+)?([a-zA-Z0-9_\-\.\s]+)", clean_cmd)
        if target_f:
            folder_name = target_f.group(1) or target_f.group(2) or "dummy_folder"
            loc = target_f.group(3) or ""
            is_vscode = any(v in loc.lower() for v in ["code", "vscode", "vs code"])
            res = await registry.execute("create_directory", path=folder_name, in_vscode=is_vscode)
            return res.get("result", f"Created folder '{folder_name}', Sir.")

        # 2. Simple folder creation: "create a folder called test_folder", "create directory new_src"
        simple_f = re.search(r"(?:create|make|add)\s+(?:a\s+)?(?:dummy\s+)?([a-zA-Z0-9_\-]+)?\s*(?:folder|directory)(?:\s+(?:called|named)\s+([a-zA-Z0-9_\-]+))?", clean_cmd)
        if simple_f:
            folder_name = simple_f.group(1) or simple_f.group(2) or "new_folder"
            if folder_name.lower() not in ("a", "the", "in", "for"):
                res = await registry.execute("create_directory", path=folder_name)
                return res.get("result", f"Created folder '{folder_name}', Sir.")

        # 3. Folder deletion: "delete the demo folder", "delete folder test_app", "remove directory new_folder"
        del_f = re.search(r"(?:delete|remove|erase|destroy)\s+(?:the\s+)?(?:dummy\s+)?(?:folder|directory)\s+([a-zA-Z0-9_\-\.\s]+?)(?:\s+for\s+me|\s+please)?$", clean_cmd)
        if not del_f:
            del_f = re.search(r"(?:delete|remove|erase|destroy)\s+(?:the\s+)?([a-zA-Z0-9_\-]+)\s+(?:folder|directory)(?:\s+for\s+me|\s+please)?$", clean_cmd)
        if del_f:
            folder_name = del_f.group(1).strip()
            if folder_name.lower() not in ("a", "the", "my", "this", "all", "it"):
                if not await consent_manager.confirm("delete_directory", {"path": folder_name}):
                    return "Understood, I won't delete it."
                res = await registry.execute("delete_directory", path=folder_name)
                return res.get("result", f"Deleted folder '{folder_name}', Sir.")

        # "open explorer", "open file explorer", "show in explorer"
        if any(eq in text for eq in ["open explorer", "open file explorer", "open in explorer", "show in explorer", "open this in explorer"]):
            res = await registry.execute("open_in_explorer", path=".")
            return res.get("result", "Opening File Explorer, Sir.")

        # "find file settings.toml", "search for file main.py"
        find_match = re.search(r"(?:find|search\s+for)\s+(?:file\s+|folder\s+)?([a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+)", text)
        if find_match:
            fname = find_match.group(1).strip()
            res = await registry.execute("search_files", query=fname)
            return res.get("result")

        # ── YouTube Channels & Videos ─────────────────────────────────────
        # 1. Video Click / Selection: "open the first video", "play the first video", "click first video", "select the second video"
        vid_click = re.search(r"(?:open|play|click|select|watch)\s+(?:the\s+)?(first|second|third|fourth|1st|2nd|3rd|4th|\d+)\s+video", text)
        if not vid_click:
            vid_click = re.search(r"(?:open|play|click|select|watch)\s+(?:the\s+)?(first|second|third|fourth|1st|2nd|3rd|4th|\d+)\s+video", clean_cmd)
        if vid_click:
            idx_map = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4}
            raw_idx = vid_click.group(1).lower()
            idx = idx_map.get(raw_idx, 1)
            res = await registry.execute("click_active_video", index=idx)
            return res.get("result", f"Selecting and playing video #{idx}, Sir.")

        # 2. Most watched video: "open his most watched video", "can you open the most watched video of Brem"
        mw_match = re.search(r"(?:open|play|watch)\s+(?:his|the|her|their)?\s*(?:most\s+watched|most\s+popular|top)\s+video(?:\s+(?:of|by|from|for)\s+(.+))?", text)
        if mw_match:
            target = mw_match.group(1)
            if not target or not target.strip():
                target = "Dream"
            target = target.strip().rstrip(".!?")
            search_q = f"{target} most watched video"
            res = await registry.execute("play_youtube_video", query=search_q)
            return res.get("result", f"Playing {search_q} on YouTube, Sir.")

        # 3. Clean channel searches: "search for Yaboy Roshi's youtube channel", "open dreams channel", "watch dream's channel"
        clean_for_ch = re.sub(r"[?!.,]", " ", text)
        clean_for_ch = re.sub(r"\s+", " ", clean_for_ch).strip()

        is_new_tab = any(kw in text.lower() for kw in ["new tab", "another tab", "different tab"])
        is_new_win = any(kw in text.lower() for kw in ["new window", "another window", "another instance"])
        force_new = is_new_tab or is_new_win

        # Close the active browser tab: "close this tab", "remove this tab", "close the tab you opened"
        if re.search(r"(?:close|remove|delete)\s+(?:this|that|the|current|it)?\s*tab", text.lower()):
            res = await registry.execute("close_browser_tab")
            return res.get("result", "Closed the active browser tab, Sir.")

        # ── Browser navigation fast-paths (operate on the user's real browser) ──
        low = text.lower()
        if low in ("go back", "browser back", "navigate back", "back") or re.search(r"\bgo\s+back\b", low):
            return (await registry.execute("browser_back")).get("result", "Went back, Sir.")
        if re.search(r"\bgo\s+forward\b", low) or low in ("go forward", "browser forward", "forward"):
            return (await registry.execute("browser_forward")).get("result", "Went forward, Sir.")
        if re.search(r"\b(refresh|reload)\b.*\b(page|tab|browser)\b", low) or low in ("refresh", "reload", "refresh the page", "reload the page"):
            return (await registry.execute("browser_refresh")).get("result", "Refreshed the page, Sir.")
        if re.search(r"(?:reopen|restore|bring back)\s+(?:the\s+)?(?:last\s+)?(?:closed\s+)?tab", low):
            return (await registry.execute("reopen_closed_tab")).get("result", "Reopened the last closed tab, Sir.")
        if re.search(r"\b(?:next|switch)\s+tab\b", low) or low == "next tab":
            return (await registry.execute("switch_browser_tab", direction="next")).get("result", "Switched tab, Sir.")
        if re.search(r"\bprevious\s+tab\b|\bprev\s+tab\b", low):
            return (await registry.execute("switch_browser_tab", direction="previous")).get("result", "Switched tab, Sir.")
        if re.search(r"\bzoom\s+in\b", low):
            return (await registry.execute("browser_zoom", level="in")).get("result", "Zoomed in, Sir.")
        if re.search(r"\bzoom\s+out\b", low):
            return (await registry.execute("browser_zoom", level="out")).get("result", "Zoomed out, Sir.")
        if re.search(r"(?:scroll)\s+(?:the\s+page\s+)?down", low):
            return (await registry.execute("browser_scroll", direction="down")).get("result", "Scrolled down, Sir.")
        if re.search(r"(?:scroll)\s+(?:the\s+page\s+)?up", low):
            return (await registry.execute("browser_scroll", direction="up")).get("result", "Scrolled up, Sir.")

        clean_for_ch = re.sub(r"\s+(?:in|on)\s+(?:a\s+)?(?:new\s+tab|new\s+window|another\s+tab|another\s+window)", "", clean_for_ch, flags=re.IGNORECASE).strip()

        had_channel_kw = "channel" in clean_for_ch.lower()
        ch_match = re.search(r"(?:open|search|go\s+to|show\s+me|watch)\s+(?:up\s+)?(.+?)\s+(?:channel(?:\s+on\s+youtube)?|on\s+youtube)", clean_for_ch)
        if ch_match:
            raw_ch = ch_match.group(1).strip()
            # Strip inner conversational wrappers: "and search for", "and open", "for"
            clean_ch = re.sub(r"^(?:(?:and\s+)?(?:search|open|find|go\s+to|watch)\s+(?:for\s+)?|for\s+)+", "", raw_ch, flags=re.IGNORECASE).strip()
            clean_ch = re.sub(r"['’]s$", "", clean_ch).strip()
            if clean_ch and len(clean_ch) > 2:
                if had_channel_kw:
                    search_target = clean_ch if clean_ch.endswith("channel") else f"{clean_ch} channel"
                else:
                    search_target = clean_ch
                res = await registry.execute("search_youtube", query=search_target, force_new=force_new, new_tab=is_new_tab)
                return res.get("result", f"Opening {search_target} on YouTube, Sir.")

        if text in ("open youtube", "open youtube in brave", "launch youtube", "go to youtube"):
            res = await registry.execute("open_website", url="https://www.youtube.com", force_new=force_new, new_tab=is_new_tab)
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
            m = re.search(pattern, clean_for_ch)
            if m:
                query = m.group(1).strip()
                query = re.sub(r"^(?:some|a|the)\s+", "", query).strip()
                if query:
                    search_q = f"{query} videos" if not query.endswith("videos") else query
                    res = await registry.execute("search_youtube", query=search_q, force_new=force_new, new_tab=is_new_tab)
                    return res.get("result", f"Opening {search_q} on YouTube, Sir.")

        # ── WhatsApp Messaging & Management ──────────────────────────────
        # "send a message on academic group", "I want to send a message on a whatsapp group"
        wa_match = re.search(r"(?:send\s+(?:a\s+)?message\s+(?:to|on)\s+)(?:a\s+|the\s+)?([a-zA-Z0-9_\-\s]+?)(?:\s+saying\s+(.+))?$", clean_cmd)
        if wa_match:
            chat = wa_match.group(1).strip()
            msg = wa_match.group(2) or ""
            if chat.lower() in ("whatsapp", "whatsapp group", "what-up", "what up", "group"):
                from jarvis.tools.whatsapp_control import _focus_whatsapp
                _focus_whatsapp()
                return "I have opened WhatsApp, Sir. Which contact or group would you like to message?"
            else:
                res = await registry.execute("send_whatsapp_message", chat_name=chat, message=msg)
                return res.get("result")

        if any(wq in text or wq in clean_cmd for wq in ["open whatsapp", "launch whatsapp", "start whatsapp", "switch to whatsapp"]):
            res = await registry.execute("open_whatsapp_chat", chat_name="")
            return "Opening WhatsApp for you, Sir."

        # "read messages on academic group", "read whatsapp messages"
        wa_read = re.search(r"(?:read|check|summarize)\s+(?:my\s+|the\s+)?(?:messages|chat)\s*(?:on|in|from)?\s*([a-zA-Z0-9_\-\s]*)", clean_cmd)
        if wa_read and ("whatsapp" in text or "message" in text or "chat" in text):
            target_chat = wa_read.group(1).strip().replace("whatsapp", "").strip()
            res = await registry.execute("read_whatsapp_messages", chat_name=target_chat)
            return res.get("result")

        # ── MCP Server Dynamic Addition ───────────────────────────────────
        # "add stitch mcp", "add stitch mcb", "can you add stitch mcp in this workspace"
        mcp_add_match = re.search(r"(?:add|install|configure)\s+([a-zA-Z0-9_\-]+)\s+(?:mcp|mcb)(?:\s+server)?", text)
        if mcp_add_match:
            server_name = mcp_add_match.group(1).strip()
            res = await registry.execute("add_mcp_server", name=server_name)
            return res.get("result")

        # ── Screenshot & Display ──────────────────────────────────────────
        if any(sq in text for sq in [
            "take a screenshot and show me", "take a screenshot and put it up",
            "put up the screenshot", "show me a screenshot", "show screenshot", "capture screen and show"
        ]):
            res = await registry.execute("capture_screen", show_image=True)
            return res.get("result")

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

        # ── Focus / Switch to an already-open app ─────────────────────────
        # "switch to brave", "focus on vs code", "show me brave", "jarvis focus brave",
        # "bring up vs code", "go to brave". NEVER launches a new instance.
        focus_match = re.search(
            r"^(?:jarvis\s+)?(?:switch(?:\s+back)?\s+to|focus(?:\s+on)?|show\s+me|bring\s+up|go\s+to|jump\s+to)\s+(?:the\s+)?([a-zA-Z0-9_\-\.\s]+?)(?:\s+window|\s+please|\s+for\s+me|\s+again)?$",
            clean_cmd
        )
        if not focus_match and clean_cmd in ("focus", "jarvis focus"):
            # Bare "focus" with no target — ask which app rather than guessing.
            return "Which application should I switch to, Sir?"
        if focus_match:
            app_target = focus_match.group(1).strip().lower()
            app_target = re.sub(r"\b(?:v\.s\.|v\.\s*s\.|v\s+s)\s*code\b", "vscode", app_target)
            FOCUS_DISALLOWED = [
                "video", "channel", "whatsapp", "chat", "message", "website", "url",
                "file", "folder", "directory", "youtube", "google", "mail", "email",
                "screen", "tab", "mcp", "dashboard", "music", "song", "track", "next", "previous",
            ]
            if app_target and not any(dk in app_target for dk in FOCUS_DISALLOWED):
                res = await registry.execute("focus_application", app_name=app_target)
                return res.get("result", f"Switching to {app_target}, Sir.")

        # ── Process Launching & Killing ───────────────────────────────────
        # Matches "then you open vs code for me", "can you open blender", "open brave", "launch vscode", "start notepad"
        launch_match = re.search(
            r"^(?:open|launch|start)\s+([a-zA-Z0-9_\-\.\s]+)$",
            clean_cmd
        )
        if not launch_match:
            launch_match = re.search(
                r"(?:can\s+you\s+|could\s+you\s+|then\s+you\s+|please\s+|just\s+|i\s+want\s+(?:you\s+)?to\s+)?(?:open|launch|start)\s+(?:up\s+)?(?:the\s+)?([a-zA-Z0-9_\-\.\s]+?)(?:\s+for\s+me|\s+please)?$",
                text
            )

        if launch_match:
            app_target = launch_match.group(1).strip().lower()
            # Clean app target
            app_target = re.sub(r"\b(?:v\.s\.|v\.\s*s\.|v\s+s)\s*code\b", "vscode", app_target)

            # Strict guard against non-applications: videos, channels, whatsapp, websites, screens
            DISALLOWED_KEYWORDS = [
                "video", "videos", "channel", "first", "second", "third", "fourth", "1st", "2nd", "3rd",
                "most watched", "most popular", "whatsapp", "what-up", "chat", "message", "group",
                "website", "url", "file", "folder", "directory", "youtube", "google", "mail", "email",
                "screen", "screenshot", "mcp", "mcb", "stitch"
            ]
            if not any(dk in app_target for dk in DISALLOWED_KEYWORDS):
                res = await registry.execute("launch_application", app_name=app_target)
                return res.get("result", f"Opening {app_target}, Sir.")

        # "close brave", "can you close vs code", "close vs code please", "close vs code if i ask it too", "exit discord", "stop blender"
        kill_regex = r"(?:can\s+you\s+|could\s+you\s+|please\s+|just\s+|i\s+want\s+(?:you\s+)?to\s+)?(?:close|kill|terminate|exit|stop|shut\s*down)\s+(?:down\s+)?(?:all\s+)?(?:instances?\s+of\s+)?(?:the\s+)?([a-zA-Z0-9_\-\.\s]+?)(?:\s+for\s+me|\s+please|\s+if\s+i\s+ask(?:\s+it)?(?:\s+too)?|\s+now)?$"
        kill_match = re.search(kill_regex, clean_cmd)
        if not kill_match:
            kill_match = re.search(kill_regex, text)
        if kill_match:
            app_target = kill_match.group(1).strip()
            # Normalize common spoken variations
            app_target = re.sub(r"\b(?:v\.s\.|v\.\s*s\.|v\s+s)\s*code\b", "vscode", app_target)
            DISALLOWED_KILL = ["music", "video", "listening", "mode", "tab", "file", "folder", "screen", "dummy"]
            if not any(dk in app_target for dk in DISALLOWED_KILL):
                if not await consent_manager.confirm("kill_process", {"process_name": app_target}):
                    return "Understood, I'll leave it open."
                res = await registry.execute("kill_process", process_name=app_target)
                return res.get("result", f"Closed {app_target}, Sir.")

        # ── Clipboard & Network ───────────────────────────────────────────
        if text in ("read clipboard", "what's on my clipboard", "what is on my clipboard", "clipboard content"):
            res = await registry.execute("get_clipboard")
            return res.get("result")

        if text in ("what is my ip", "what's my ip", "check ip", "network info", "ip address"):
            res = await registry.execute("get_network_info")
            return res.get("result")

        # ── Capabilities & Memory Fast-Paths ─────────────────────────────
        capability_triggers = [
            "what can you do", "what are your capabilities", "what are your functionalities",
            "what functionalities do you have", "tell me what you can do", "what are your features",
            "what do you do", "how can you help me"
        ]
        if any(ct in text for ct in capability_triggers):
            res = await registry.execute("get_jarvis_capabilities")
            return res.get("result")

        memory_queries = [
            "what do you remember about me", "what do you know about me", "recall my preferences",
            "what is my name", "what's my name", "who am i", "tell me what you remember"
        ]
        if any(mq in text for mq in memory_queries):
            res = await registry.execute("recall_user_memories")
            return res.get("result")

        # "remember my name is Om", "call me Om", "remember that I prefer dark mode"
        remember_match = re.search(r"(?:remember\s+(?:that\s+)?)?(?:my\s+name\s+is|call\s+me)\s+([a-zA-Z]+)", text)
        if remember_match:
            name_val = remember_match.group(1).title()
            res = await registry.execute("save_user_memory", fact=f"User's name is {name_val}")
            return res.get("result")

        if text.startswith("remember that ") or text.startswith("remember "):
            fact_val = re.sub(r"^remember\s+(?:that\s+)?", "", text).strip()
            if fact_val:
                res = await registry.execute("save_user_memory", fact=fact_val)
                return res.get("result")

        if text in ("list mcp servers", "show mcp servers", "what mcps are installed", "what mcp servers are there"):
            res = await registry.execute("list_mcp_servers")
            return res.get("result")

        # ── Open-web knowledge Q&A (cloud answer, not the local model) ────
        # Runs LAST so every PC/self/specific handler above wins first. Only
        # fires on factual questions that are NOT about the user's own machine.
        if self._is_web_knowledge_question(text):
            res = await registry.execute("answer_from_web", question=utterance)
            return res.get("result")

        return None

    # Factual question starters that usually want an open-web answer.
    _KNOWLEDGE_START = re.compile(
        r"^(?:what|whats|what's|who|whose|whom|when|where|why|how|which|define|"
        r"tell me about|give me)\b"
    )
    # Tokens that mean the question is about the user's own PC/context/self —
    # those must stay local and never go to the cloud.
    _KNOWLEDGE_EXCLUDE = re.compile(
        r"\b(you|your|yourself|jarvis|my|mine|myself|this (?:file|code|screen|document|window)|"
        r"screen|desktop|clipboard|volume|battery|time|date|ip|the day today)\b"
    )

    def _is_web_knowledge_question(self, text: str) -> bool:
        if not self._KNOWLEDGE_START.match(text):
            return False
        if self._KNOWLEDGE_EXCLUDE.search(text):
            return False
        # Require a bit of substance (avoid one-word fragments).
        return len(text.split()) >= 3

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
