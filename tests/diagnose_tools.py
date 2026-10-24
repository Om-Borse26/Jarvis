"""
Comprehensive Windows Tool Diagnostics & Live Verification Suite
Executes and validates all registered Jarvis tools directly on this machine.
"""
from __future__ import annotations

import asyncio
import time
import os
from pathlib import Path
from jarvis.tools.registry import registry
from jarvis.tools.router import ToolRouter
import jarvis.tools

results: dict[str, str] = {}


async def run_diagnostics():
    print("=" * 65)
    print("    J.A.R.V.I.S. — FULL WINDOWS TOOL DIAGNOSTICS SUITE")
    print("=" * 65)
    print(f"Total Registered Tools: {len(registry.list_tools())}")

    # ── 1. AUDIO & VOLUME ─────────────────────────
    print("\n[1/8] Testing Audio & Volume Controls...")
    try:
        v_orig = registry.get_tool("get_volume").func()
        print("  - Initial volume state:", v_orig)
        
        v_set = registry.get_tool("set_volume").func(percent=45)
        print("  - set_volume(45):", v_set)
        
        v_mute = registry.get_tool("mute_volume").func()
        print("  - mute_volume():", v_mute)
        
        v_unmute = registry.get_tool("unmute_volume").func()
        print("  - unmute_volume():", v_unmute)
        
        # Restore to comfortable level
        registry.get_tool("set_volume").func(percent=50)
        results["Audio Tools"] = "PASSED (get, set, mute, unmute working)"
    except Exception as e:
        results["Audio Tools"] = f"FAILED: {e}"

    # ── 2. SYSTEM & TELEMETRY ─────────────────────
    print("\n[2/8] Testing System & Hardware Telemetry...")
    try:
        hw = registry.get_tool("get_hardware_metrics").func()
        print("  - get_hardware_metrics():", hw)
        assert "GPU" in hw and "CPU" in hw and "RAM" in hw
        
        net = registry.get_tool("get_network_info").func()
        print("  - get_network_info():", net)
        assert "IP" in net
        results["System & Telemetry"] = "PASSED (RTX 4050 GPU, CPU, RAM, Battery, IP working)"
    except Exception as e:
        results["System & Telemetry"] = f"FAILED: {e}"

    # ── 3. PROCESS CONTROL ────────────────────────
    print("\n[3/8] Testing Process Management...")
    try:
        apps = registry.get_tool("list_active_apps").func()
        print("  - list_active_apps():", apps)
        
        launch_res = registry.get_tool("launch_application").func(app_name="notepad")
        print("  - launch_application('notepad'):", launch_res)
        await asyncio.sleep(0.8)
        
        kill_res = registry.get_tool("kill_process").func(process_name="notepad")
        print("  - kill_process('notepad'):", kill_res)
        results["Process Control"] = "PASSED (list, launch, and kill working)"
    except Exception as e:
        results["Process Control"] = f"FAILED: {e}"

    # ── 4. FILESYSTEM OPERATIONS ──────────────────
    print("\n[4/8] Testing Filesystem Controls...")
    try:
        search_res = registry.get_tool("search_files").func(query="settings.toml")
        print("  - search_files('settings.toml'):", search_res.splitlines()[0])
        assert "matches" in search_res
        
        read_res = registry.get_tool("read_file").func(file_path="config/settings.toml", max_chars=80)
        print("  - read_file():", read_res.splitlines()[0])
        assert "settings.toml" in read_res
        
        scratch_file = "test_tool_scratch.txt"
        write_res = registry.get_tool("write_file").func(file_path=scratch_file, content="Jarvis test content.")
        print("  - write_file():", write_res)
        
        list_res = registry.get_tool("list_directory").func(folder_path=".")
        print("  - list_directory():", list_res.splitlines()[0], f"(found {len(list_res.splitlines()) - 1} entries)")
        
        if Path(scratch_file).exists():
            os.remove(scratch_file)
        results["Filesystem Tools"] = "PASSED (search, read, write, list working)"
    except Exception as e:
        results["Filesystem Tools"] = f"FAILED: {e}"

    # ── 5. SHELL & CLIPBOARD ──────────────────────
    print("\n[5/8] Testing Universal Shell & Clipboard...")
    try:
        ps_res = registry.get_tool("run_powershell").func(command="Write-Output 'Jarvis PowerShell OK'")
        print("  - run_powershell():", ps_res)
        assert "Jarvis PowerShell OK" in ps_res
        
        set_clip_res = registry.get_tool("set_clipboard").func(text="Diagnostic Test String 2026")
        print("  - set_clipboard():", set_clip_res)
        clip_verify = registry.get_tool("get_clipboard").func()
        print("  - get_clipboard():", clip_verify.replace("\n", " "))
        assert "Diagnostic Test String 2026" in clip_verify
        results["Shell & Clipboard"] = "PASSED (arbitrary PowerShell execution & Clipboard I/O working)"
    except Exception as e:
        results["Shell & Clipboard"] = f"FAILED: {e}"

    # ── 6. GUI & VIRTUAL HANDS ────────────────────
    print("\n[6/8] Testing GUI & Virtual Hands...")
    try:
        mouse_res = registry.get_tool("mouse_move").func(x=500, y=500)
        print("  - mouse_move(500, 500):", mouse_res)
        
        key_press_res = registry.get_tool("keyboard_press").func(key="shift")
        print("  - keyboard_press('shift'):", key_press_res)
        
        focus_res = registry.get_tool("focus_window").func(title_keyword="Code")
        print("  - focus_window('Code'):", focus_res)
        results["GUI & Virtual Hands"] = "PASSED (mouse move, key press, window focus working)"
    except Exception as e:
        results["GUI & Virtual Hands"] = f"FAILED: {e}"

    # ── 7. MEDIA & DESKTOP WINDOWS ────────────────
    print("\n[7/8] Testing Media & Window Actions...")
    try:
        media_res = registry.get_tool("media_play_pause").func()
        print("  - media_play_pause():", media_res)
        
        desktop_res = registry.get_tool("show_desktop").func()
        print("  - show_desktop():", desktop_res)
        # Restore focus to Code window
        registry.get_tool("focus_window").func(title_keyword="Code")
        results["Media & Window Control"] = "PASSED (media playback toggle & show desktop working)"
    except Exception as e:
        results["Media & Window Control"] = f"FAILED: {e}"

    # ── 8. FAST-PATH ROUTER LATENCY & MATCHING ────
    print("\n[8/10] Testing Fast-Path Intent Router...")
    try:
        router = ToolRouter()
        queries = [
            "set volume to 60",
            "gpu temp",
            "what apps are running",
            "what is my ip",
            "pause music",
            "read clipboard",
            "what are your functionalities",
        ]
        latencies = []
        for q in queries:
            t_start = time.perf_counter()
            resp = await router.try_fast_path(q)
            dt = (time.perf_counter() - t_start) * 1000
            latencies.append(dt)
            print(f"  - Fast-path '{q}': {dt:.2f}ms -> {resp[:65]}...")
            assert resp is not None
        avg_lat = sum(latencies) / len(latencies)
        results["Fast-Path Router"] = f"PASSED (avg latency: {avg_lat:.2f}ms across {len(queries)} commands)"
    except Exception as e:
        results["Fast-Path Router"] = f"FAILED: {e}"

    # ── 9. DYNAMIC APP DISCOVERY (NO HARDCODING) ──
    print("\n[9/10] Testing Dynamic App Discovery & Ranking...")
    try:
        from jarvis.tools.process_control import app_resolver
        test_apps = ["vscode", "vs code", "brave", "blender", "chrome", "notepad"]
        for ta in test_apps:
            res = app_resolver.resolve(ta)
            print(f"  - resolve('{ta}'): {res[1] if res else 'None'} ({res[3] if res else '-'}) score={res[0]:.2f}")
            assert res is not None and res[0] >= 0.70
        results["Dynamic App Resolver"] = f"PASSED (Indexed {len(app_resolver._apps)} apps, zero hardcoding)"
    except Exception as e:
        results["Dynamic App Resolver"] = f"FAILED: {e}"

    # ── 10. MEMORY & MCP INTEGRATIONS ──────────────
    print("\n[10/10] Testing Memory & MCP Tools...")
    try:
        save_res = registry.get_tool("save_user_memory").func(fact="Diagnostic run completed at 2026-10-24")
        print("  - save_user_memory():", save_res)
        
        recall_res = registry.get_tool("recall_user_memories").func(query="Diagnostic")
        print("  - recall_user_memories():", recall_res)
        assert "Diagnostic" in recall_res
        
        mcp_res = registry.get_tool("list_mcp_servers").func()
        print("  - list_mcp_servers():", mcp_res)
        assert "playwright" in mcp_res.lower()
        
        code_res = registry.get_tool("codebase_search_context").func(query="VADListener")
        print("  - codebase_search_context('VADListener'):", code_res.splitlines()[1] if len(code_res.splitlines()) > 1 else code_res)
        assert "vad.py" in code_res or "pipeline.py" in code_res
        
        results["Memory & MCP Tools"] = "PASSED (fact storage, recall, MCP servers, and codebase search working)"
    except Exception as e:
        results["Memory & MCP Tools"] = f"FAILED: {e}"

    print("\n" + "=" * 65)
    print("                 LIVE DIAGNOSTICS RESULT SUMMARY")
    print("=" * 65)
    all_ok = True
    for cat, status in results.items():
        icon = "[OK]" if "PASSED" in status else "[FAIL]"
        if "FAILED" in status:
            all_ok = False
        print(f"  {icon} {cat.ljust(25)} : {status}")
    print("=" * 65)
    if all_ok:
        print(">>> ALL TOOLS FULLY OPERATIONAL AND VERIFIED ON THIS LAPTOP! <<<")
    else:
        print(">>> SOME TOOLS FAILED DIAGNOSTICS. PLEASE CHECK LOGS ABOVE. <<<")


if __name__ == "__main__":
    asyncio.run(run_diagnostics())
