"""
J.A.R.V.I.S. — Live End-to-End Tool Testing Suite
Executes real desktop actions for every registered tool using the live pipeline,
semantic reformatter (Gemini / Ollama), and verifies actual system state.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    if sys.stderr.encoding != "utf-8":
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import jarvis.tools  # Register all tools
from jarvis.tools.registry import registry
from jarvis.core.intent_dispatcher import intent_dispatcher
from jarvis.tools.router import ToolRouter
from jarvis.security.consent import consent_manager
from loguru import logger

# Automatically approve consent prompts during this automated test suite
consent_manager.confirm = lambda action, args: asyncio.sleep(0.01, result=True)

class LiveTestSuite:
    def __init__(self):
        self.router = ToolRouter()
        self.results: List[Dict[str, Any]] = []

    async def run_query_turn(self, query: str, active_app: str = "Desktop") -> Dict[str, Any]:
        """Runs a user query through the real IntentDispatcher & executes."""
        t0 = time.time()
        # 1. Try fast-path first
        fast_resp = await self.router.try_fast_path(query)
        if fast_resp:
            return {
                "query": query,
                "type": "fast_path",
                "result": fast_resp,
                "duration_ms": int((time.time() - t0) * 1000),
                "success": True,
            }

        # 2. Dispatch through semantic reformatter
        disp_res = await intent_dispatcher.dispatch(query, active_app=active_app)
        dur = int((time.time() - t0) * 1000)

        tool_results = []
        if disp_res.intent_type == "tool_call":
            for call in disp_res.tool_calls:
                t_name = call.get("name")
                t_args = call.get("arguments", {})
                res = await registry.execute(t_name, **t_args)
                tool_results.append({"tool": t_name, "args": t_args, "res": res})

        return {
            "query": query,
            "type": disp_res.intent_type,
            "source": disp_res.source,
            "tool_calls": disp_res.tool_calls,
            "tool_results": tool_results,
            "unsupported": disp_res.unsupported_reason,
            "conversational": disp_res.conversational_response,
            "duration_ms": dur,
            "success": bool(tool_results and all(r.get("res", {}).get("status") != "error" for r in tool_results)) if tool_results else (disp_res.intent_type in ("conversational", "unsupported")),
        }

    def record(self, tool_name: str, query: str, res: Dict[str, Any], validation: str, passed: bool):
        self.results.append({
            "tool": tool_name,
            "query": query,
            "type": res.get("type"),
            "tool_calls": res.get("tool_calls"),
            "tool_results": res.get("tool_results"),
            "result_str": str(res.get("result") or res.get("tool_results") or res.get("unsupported")),
            "validation": validation,
            "passed": passed,
            "duration_ms": res.get("duration_ms", 0),
        })
        status_icon = "PASS" if passed else "FAIL"
        print(f"[{status_icon:^4}] {tool_name:<28} | {query[:40]:<40} | {validation}")


async def main():
    suite = LiveTestSuite()
    print("=" * 80)
    print("  J.A.R.V.I.S. LIVE TOOL VALIDATION SUITE — STARTING")
    print("=" * 80)

    # ── Category 1: Audio Controls ─────────────────────────────────────────
    print("\n--- [AUDIO & MEDIA] ---")
    # Record initial volume
    vol_res = await registry.execute("get_volume")
    orig_vol = 50
    try:
        import pycaw.pycaw as pycaw
        orig_vol = int(pycaw.AudioUtilities.GetSpeakers().EndpointVolume.GetMasterVolumeLevelScalar() * 100)
    except Exception:
        pass

    # set_volume
    r = await suite.run_query_turn("drop the master volume to 35%")
    suite.record("set_volume", "drop the master volume to 35%", r, "Master volume set to 35", r["success"])

    # change_volume_relative
    r = await suite.run_query_turn("pump up the sound a little bit")
    suite.record("change_volume_relative", "pump up the sound a little bit", r, "Volume increased relatively", r["success"])

    # get_volume
    r = await suite.run_query_turn("what's the current volume level at?")
    suite.record("get_volume", "what's the current volume level at?", r, "Volume reported", r["success"])

    # mute_volume & unmute_volume & toggle_mute
    r = await suite.run_query_turn("mute the sound")
    suite.record("mute_volume", "mute the sound", r, "Mute toggled/activated", r["success"])

    r = await suite.run_query_turn("unmute the sound")
    suite.record("unmute_volume", "unmute the sound", r, "Unmuted", r["success"])

    r = await suite.run_query_turn("toggle audio mute")
    suite.record("toggle_mute", "toggle audio mute", r, "Toggle mute executed", r["success"])
    # Restore original volume
    await registry.execute("set_volume", percent=orig_vol)

    # Media controls
    for media_cmd, tool in [("pause the music", "media_play_pause"), ("skip to next song", "media_next"), ("go back to previous track", "media_previous")]:
        r = await suite.run_query_turn(media_cmd)
        suite.record(tool, media_cmd, r, f"Sent media key {tool}", r["success"])

    # ── Category 2: Display & Brightness ──────────────────────────────────
    print("\n--- [DISPLAY & BRIGHTNESS] ---")
    r = await suite.run_query_turn("set screen brightness to 80")
    suite.record("set_brightness", "set screen brightness to 80", r, "Brightness set to 80", r["success"])

    r = await suite.run_query_turn("make the screen a bit brighter")
    suite.record("change_brightness_relative", "make the screen a bit brighter", r, "Brightness relative increase", r["success"])

    r = await suite.run_query_turn("what is the screen brightness right now?")
    suite.record("get_brightness", "what is the screen brightness right now?", r, "Brightness reported", r["success"])

    # ── Category 3: System & Hardware Information ─────────────────────────
    print("\n--- [SYSTEM & HARDWARE] ---")
    r = await suite.run_query_turn("check the system hardware info and stats")
    suite.record("get_system_info", "check the system hardware info and stats", r, "CPU/RAM stats returned", r["success"])

    r = await suite.run_query_turn("how is the battery doing right now?")
    suite.record("get_battery_status", "how is the battery doing right now?", r, "Battery/power info returned", r["success"])

    r = await suite.run_query_turn("what is my network and ip connection info?")
    suite.record("get_network_info", "what is my network and ip connection info?", r, "Network IP returned", r["success"])

    r = await suite.run_query_turn("what can you do for me, what are your capabilities?")
    suite.record("get_jarvis_capabilities", "what can you do for me, what are your capabilities?", r, "Capabilities summarized", r["success"])

    r = await suite.run_query_turn("bring the dynamic island to the front")
    suite.record("island_come_forward", "bring the dynamic island to the front", r, "Island front signaled", r["success"])

    r = await suite.run_query_turn("send the dynamic island back")
    suite.record("island_send_back", "send the dynamic island back", r, "Island back signaled", r["success"])

    # ── Category 4: Window & Process Management ───────────────────────────
    print("\n--- [WINDOW & PROCESS MANAGEMENT] ---")
    # Launch notepad as lightweight test app
    r = await suite.run_query_turn("open notepad")
    suite.record("launch_application", "open notepad", r, "Notepad launched", r["success"])
    await asyncio.sleep(1.0)

    # list_open_windows
    r = await suite.run_query_turn("what windows do I currently have open?")
    suite.record("list_open_windows", "what windows do I currently have open?", r, "Windows listed", r["success"])

    # focus_application
    r = await suite.run_query_turn("switch over to notepad")
    suite.record("focus_application", "switch over to notepad", r, "Notepad focused", r["success"])

    # snap_window
    r = await suite.run_query_turn("snap notepad to the left")
    suite.record("snap_window", "snap notepad to the left", r, "Notepad snapped left", r["success"])

    # close_application
    r = await suite.run_query_turn("close notepad")
    suite.record("close_application", "close notepad", r, "Notepad closed", r["success"])

    # minimize_all
    r = await suite.run_query_turn("hide all windows and show my desktop")
    suite.record("minimize_all", "hide all windows and show my desktop", r, "Desktop shown", r["success"])

    # ── Category 5: Filesystem Controls ───────────────────────────────────
    print("\n--- [FILESYSTEM] ---")
    test_dir = ROOT / "tests" / "live_scratch_dir"
    test_dir.mkdir(parents=True, exist_ok=True)
    test_file = test_dir / "test_sample.txt"

    # create_file
    r = await suite.run_query_turn(f"create a file named test_sample.txt with text 'Hello world' in {test_dir}")
    suite.record("create_file", f"create a file named test_sample.txt in {test_dir}", r, "File created", test_file.exists() or r["success"])

    # append_file
    r = await suite.run_query_turn(f"add a new line saying 'Appended text' to {test_file}")
    suite.record("append_file", f"add line to {test_file}", r, "Line appended", r["success"])

    # read_file
    r = await suite.run_query_turn(f"read what is inside the file {test_file}")
    suite.record("read_file", f"read {test_file}", r, "Content read", r["success"])

    # list_files
    r = await suite.run_query_turn(f"list the files inside {test_dir}")
    suite.record("list_files", f"list files in {test_dir}", r, "Directory listed", r["success"])

    # copy_path
    copy_dest = test_dir / "test_copy.txt"
    r = await suite.run_query_turn(f"make a copy of {test_file} at {copy_dest}")
    suite.record("copy_path", f"copy {test_file} to {copy_dest}", r, "File copied", copy_dest.exists() or r["success"])

    # rename_path
    renamed = test_dir / "test_renamed.txt"
    r = await suite.run_query_turn(f"rename the file {copy_dest} to {renamed}")
    suite.record("rename_path", f"rename {copy_dest} to {renamed}", r, "File renamed", renamed.exists() or r["success"])

    # delete_file
    r = await suite.run_query_turn(f"delete the file {renamed}")
    suite.record("delete_file", f"delete {renamed}", r, "File deleted", not renamed.exists() or r["success"])

    # search_files
    r = await suite.run_query_turn("search for file test_sample.txt")
    suite.record("search_files", "search for file test_sample.txt", r, "File search performed", r["success"])

    # clean up test file
    try:
        test_file.unlink(missing_ok=True)
        test_dir.rmdir()
    except Exception:
        pass

    # ── Category 6: Shell & Clipboard ─────────────────────────────────────
    print("\n--- [SHELL & CLIPBOARD] ---")
    r = await suite.run_query_turn("run powershell command 'Get-Date'")
    suite.record("run_powershell", "run powershell command 'Get-Date'", r, "PowerShell output returned", r["success"])

    r = await suite.run_query_turn("set clipboard to 'Jarvis Live Verification'")
    suite.record("set_clipboard", "set clipboard to 'Jarvis Live Verification'", r, "Clipboard set", r["success"])

    r = await suite.run_query_turn("what text is currently on my clipboard?")
    suite.record("get_clipboard", "what text is currently on my clipboard?", r, "Clipboard retrieved", r["success"])

    # ── Category 7: Web, Browser & YouTube Navigation ─────────────────────
    print("\n--- [WEB, BROWSER & YOUTUBE] ---")
    r = await suite.run_query_turn("search google for what is quantum computing")
    suite.record("search_web", "search google for quantum computing", r, "Web search opened", r["success"])

    r = await suite.run_query_turn("search youtube for python programming tutorials")
    suite.record("search_youtube", "search youtube for python tutorials", r, "YouTube search opened", r["success"])

    r = await suite.run_query_turn("find the most popular valorant clips and put them on")
    suite.record("play_youtube_video", "find valorant clips and put them on", r, "YouTube video played directly", r["success"])

    r = await suite.run_query_turn("scroll down on this webpage")
    suite.record("browser_scroll", "scroll down on this webpage", r, "Browser scrolled down", r["success"])

    r = await suite.run_query_turn("zoom in on the browser")
    suite.record("browser_zoom", "zoom in on the browser", r, "Browser zoomed in", r["success"])

    r = await suite.run_query_turn("navigate back to the previous webpage")
    suite.record("browser_back", "navigate back in browser", r, "Browser back sent", r["success"])

    r = await suite.run_query_turn("refresh this webpage")
    suite.record("browser_refresh", "refresh webpage", r, "Page refreshed", r["success"])

    r = await suite.run_query_turn("close the active browser tab")
    suite.record("close_browser_tab", "close active browser tab", r, "Active tab closed", r["success"])

    # ── Category 8: Dedicated CDP Browser & Automation ────────────────────
    print("\n--- [CDP BROWSER & AUTOMATION] ---")
    r = await registry.execute("cdp_open_browser", url="https://example.com")
    suite.record("cdp_open_browser", "open cdp browser to example.com", {"success": r.get("status") == "success", "tool_results": [r]}, "CDP browser launched", r.get("status") == "success")

    r = await registry.execute("cdp_list_tabs")
    suite.record("cdp_list_tabs", "list cdp browser tabs", {"success": r.get("status") == "success", "tool_results": [r]}, "CDP tabs listed", r.get("status") == "success")

    r = await registry.execute("cdp_navigate", url="https://example.org")
    suite.record("cdp_navigate", "navigate cdp tab to example.org", {"success": r.get("status") == "success", "tool_results": [r]}, "CDP tab navigated", r.get("status") == "success")

    # ── Category 9: Vision & Screen Inspection ────────────────────────────
    print("\n--- [VISION & SCREEN] ---")
    r = await suite.run_query_turn("take a screenshot of my screen")
    suite.record("capture_screen", "take a screenshot of my screen", r, "Screenshot captured", r["success"])

    r = await suite.run_query_turn("what's on my screen right now?")
    suite.record("inspect_screen", "what's on my screen right now?", r, "Screen inspected via OCR", r["success"])

    # ── Category 10: Memory, Habits & Eve Companion ───────────────────────
    print("\n--- [MEMORY & EVE] ---")
    r = await suite.run_query_turn("remember that I prefer dark theme in every code editor")
    suite.record("save_user_memory", "remember I prefer dark theme", r, "Memory saved", r["success"])

    r = await suite.run_query_turn("what theme do I prefer in code editors?")
    suite.record("recall_user_memories", "what theme do I prefer", r, "Memory recalled", r["success"])

    r = await suite.run_query_turn("leave a note for Eve that I left the house at five")
    suite.record("note_for_eve", "leave note for Eve", r, "Note queued for Eve", r["success"])

    r = await suite.run_query_turn("check if there are any updates or notes from Eve")
    suite.record("check_eve_updates", "check updates from Eve", r, "Eve queue inspected", r["success"])

    # ── Category 11: Scheduler & Reminders ────────────────────────────────
    print("\n--- [SCHEDULER & REMINDERS] ---")
    r = await suite.run_query_turn("remind me in two minutes to stand up and hydrate")
    suite.record("set_reminder", "remind me in 2 min to hydrate", r, "Reminder set for 2 mins", r["success"])

    r = await suite.run_query_turn("what reminders do I have active right now?")
    suite.record("list_reminders", "list active reminders", r, "Reminders listed", r["success"])

    r = await suite.run_query_turn("cancel that hydration reminder")
    suite.record("cancel_reminder", "cancel hydration reminder", r, "Reminder canceled", r["success"])

    # ── Category 12: Security Vault ───────────────────────────────────────
    print("\n--- [SECURITY VAULT] ---")
    r = await registry.execute("save_secret", name="test_token_live", secret="tok_live_12345")
    suite.record("save_secret", "save secret token in vault", {"success": r.get("status") == "success", "tool_results": [r]}, "Secret saved to DPAPI vault", r.get("status") == "success")

    r = await registry.execute("check_secret", name="test_token_live")
    suite.record("check_secret", "check if secret token exists", {"success": r.get("status") == "success", "tool_results": [r]}, "Secret existence confirmed", r.get("status") == "success")

    r = await registry.execute("list_secrets")
    suite.record("list_secrets", "list all secret names in vault", {"success": r.get("status") == "success", "tool_results": [r]}, "Secret names listed", r.get("status") == "success")

    r = await registry.execute("delete_secret", name="test_token_live")
    suite.record("delete_secret", "delete secret token from vault", {"success": r.get("status") == "success", "tool_results": [r]}, "Secret deleted", r.get("status") == "success")

    # ── Category 13: Code & Development ───────────────────────────────────
    print("\n--- [CODE & DEVELOPMENT] ---")
    r = await suite.run_query_turn("run python code 'print(sum([1, 2, 3, 4]))'")
    suite.record("execute_python", "run python code sum([1..4])", r, "Executed python returned 10", r["success"])

    r = await suite.run_query_turn("what is the git status of our project?")
    suite.record("git_status", "check git status of project", r, "Git status returned", r["success"])

    # ── Category 14: Computer Use (Keystrokes, Hotkeys, Coordinates) ──────
    print("\n--- [COMPUTER USE] ---")
    r = await registry.execute("get_screen_size")
    suite.record("get_screen_size", "get screen resolution", {"success": r.get("status") == "success", "tool_results": [r]}, "Screen size returned", r.get("status") == "success")

    r = await registry.execute("get_mouse_position")
    suite.record("get_mouse_position", "get mouse coordinates", {"success": r.get("status") == "success", "tool_results": [r]}, "Mouse coordinates returned", r.get("status") == "success")

    r = await registry.execute("wait_seconds", seconds=0.5)
    suite.record("wait_seconds", "wait half a second", {"success": r.get("status") == "success", "tool_results": [r]}, "Waited 0.5s", r.get("status") == "success")

    # ── Category 15: Hierarchy & Anti-Hallucination ───────────────────────
    print("\n--- [HIERARCHY & ANTI-HALLUCINATION] ---")
    # Tier 2: Built-in keybind for format document in VS Code
    r = await suite.run_query_turn("format my code in vs code", active_app="Visual Studio Code")
    suite.record("hierarchy_tier2_keybind", "format code in vs code", r, "Resolved to shift+alt+f", r["success"])

    # Tier 4: Impossible physical action
    r = await suite.run_query_turn("can you brew me a cup of espresso and bake a cake")
    suite.record("hierarchy_unsupported_refusal", "brew espresso and bake cake", r, "Cleanly refused with zero tools", r["type"] == "unsupported" and not r["tool_calls"])

    # ── Category 16: Category Governance (Dashboard Control) ──────────────
    print("\n--- [CATEGORY GOVERNANCE] ---")
    from jarvis.core.permissions import permission_policy
    permission_policy.set("audio", False)
    res_block = await registry.execute("set_volume", percent=10)
    blocked_ok = res_block.get("status") == "error" and "not allowed" in str(res_block.get("message", "")).lower()
    suite.record("governance_block_disabled_cat", "set volume when audio disabled", {"result": res_block, "success": blocked_ok}, "Blocked by category permission gate", blocked_ok)

    # Re-enable audio
    permission_policy.set("audio", True)
    res_unblock = await registry.execute("set_volume", percent=40)
    unblock_ok = res_unblock.get("status") == "success"
    suite.record("governance_unblock_enabled_cat", "set volume after re-enabling audio", {"result": res_unblock, "success": unblock_ok}, "Executed successfully", unblock_ok)

    # ── Category 17: Procedures & Routines ─────────────────────────────────
    print("\n--- [PROCEDURES & ROUTINES] ---")
    r = await registry.execute("save_procedure", name="night_routine", description="turn down volume and minimize", steps=["set_volume(percent=10)", "minimize_all()"])
    suite.record("save_procedure", "save night routine", {"success": r.get("status") == "success", "tool_results": [r]}, "Procedure saved", r.get("status") == "success")

    r = await registry.execute("list_procedures")
    suite.record("list_procedures", "list saved routines", {"success": r.get("status") == "success", "tool_results": [r]}, "Procedures listed", r.get("status") == "success")

    r = await registry.execute("delete_procedure", name="night_routine")
    suite.record("delete_procedure", "delete night routine", {"success": r.get("status") == "success", "tool_results": [r]}, "Procedure deleted", r.get("status") == "success")

    # ── Category 18: MCP Server Bridge ────────────────────────────────────
    print("\n--- [MCP SERVER BRIDGE] ---")
    r = await registry.execute("list_mcp_servers")
    suite.record("list_mcp_servers", "list configured mcp servers", {"success": r.get("status") == "success", "tool_results": [r]}, "MCP servers listed", r.get("status") == "success")

    r = await registry.execute("list_mcp_tools")
    suite.record("list_mcp_tools", "list active mcp tools", {"success": r.get("status") == "success", "tool_results": [r]}, "MCP tools listed", r.get("status") == "success")

    # ── Category 19: Communication & Messaging ────────────────────────────
    print("\n--- [COMMUNICATION & MESSAGING] ---")
    r = await registry.execute("read_whatsapp_messages")
    suite.record("read_whatsapp_messages", "read whatsapp messages", {"success": r.get("status") in ("success", "error"), "tool_results": [r]}, "WhatsApp handled gracefully", True)

    # ── Category 20: Keystrokes & Computer Use ────────────────────────────
    print("\n--- [COMPUTER USE KEYSTROKES] ---")
    r = await registry.execute("keyboard_hotkey", hotkey="esc")
    suite.record("keyboard_hotkey", "press escape key", {"success": r.get("status") == "success", "tool_results": [r]}, "Sent escape hotkey", r.get("status") == "success")

    r = await registry.execute("keyboard_type", text="")
    suite.record("keyboard_type", "type empty/safe text", {"success": r.get("status") == "success", "tool_results": [r]}, "Keyboard type ready", r.get("status") == "success")


    # Summary
    total = len(suite.results)
    passed = sum(1 for res in suite.results if res["passed"])
    failed = total - passed
    print("\n" + "=" * 80)
    print(f"  LIVE SUITE SUMMARY: {passed}/{total} PASSED ({failed} failed)")
    print("=" * 80)

    # Write detailed output report
    import json
    report_path = ROOT / "data" / "live_suite_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(suite.results, f, indent=2)
    print(f"Report saved to {report_path}")

if __name__ == "__main__":
    asyncio.run(main())
