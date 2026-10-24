"""
J.A.R.V.I.S. — Comprehensive Windows Automation & Intent Robustness Test Suite
Validates:
  1. Direct execution of EVERY Windows control tool.
  2. Fast-path intent router under tricky phrasing, accents, weird spacing, and conversational noise.
  3. LLM tool-calling fallback for non-deterministic requests.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from loguru import logger

from jarvis.tools.registry import registry
from jarvis.tools.router import ToolRouter
import jarvis.tools
from jarvis.audio.accent_normalizer import SpeechNormalizer
from jarvis.brain.ollama_client import OllamaClient
from jarvis.core.arbiter import SteerArbiter


async def run_windows_suite():
    router = ToolRouter()
    logger.info("=================================================================")
    logger.info("   J.A.R.V.I.S. — FULL WINDOWS CONTROLS STRESS & ROBUSTNESS TEST")
    logger.info("=================================================================")

    passed = 0
    failed = 0

    def check(name: str, condition: bool, detail: str = ""):
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"  [PASS] {name} -> {detail[:80]}")
        else:
            failed += 1
            print(f"  [FAIL] {name} -> {detail}")

    # =========================================================================
    # PART 1: DIRECT EXECUTION OF ALL WINDOWS TOOLS
    # =========================================================================
    print("\n--- [PART 1: DIRECT WINDOWS TOOL EXECUTION] ---")

    # 1. Volume & Audio
    v_res = await registry.execute("set_volume", percent=55)
    check("set_volume(55)", v_res.get("status") == "success", v_res.get("result", ""))

    gv_res = await registry.execute("get_volume")
    check("get_volume()", gv_res.get("status") == "success", gv_res.get("result", ""))

    cvr_res = await registry.execute("change_volume_relative", delta_percent=10)
    check("change_volume_relative(+10)", cvr_res.get("status") == "success", cvr_res.get("result", ""))

    m_res = await registry.execute("mute_volume")
    check("mute_volume()", m_res.get("status") == "success", m_res.get("result", ""))

    um_res = await registry.execute("unmute_volume")
    check("unmute_volume()", um_res.get("status") == "success", um_res.get("result", ""))

    # Restore comfortable volume
    await registry.execute("set_volume", percent=65)

    # 2. Hardware & Window Context
    hw_res = await registry.execute("get_hardware_metrics")
    check("get_hardware_metrics()", hw_res.get("status") == "success", hw_res.get("result", ""))

    net_res = await registry.execute("get_network_info")
    check("get_network_info()", net_res.get("status") == "success", net_res.get("result", ""))

    win_res = await registry.execute("get_current_active_window")
    check("get_current_active_window()", win_res.get("status") == "success", win_res.get("result", ""))

    # 3. Process Management
    proc_list = await registry.execute("list_active_apps")
    check("list_active_apps()", proc_list.get("status") == "success", proc_list.get("result", ""))

    launch_res = await registry.execute("launch_application", app_name="notepad")
    check("launch_application('notepad')", launch_res.get("status") == "success", launch_res.get("result", ""))
    time.sleep(0.5)

    kill_res = await registry.execute("kill_process", process_name="notepad")
    check("kill_process('notepad')", kill_res.get("status") == "success", kill_res.get("result", ""))

    # 4. Filesystem Controls
    test_dir = "test_jarvis_automation_dir"
    mkdir_res = await registry.execute("create_directory", path=test_dir)
    check("create_directory(test_dir)", Path(test_dir).exists(), mkdir_res.get("result", ""))

    test_file = f"{test_dir}/test_note.txt"
    wf_res = await registry.execute("write_file", file_path=test_file, content="Jarvis Windows Automation Verified")
    check("write_file()", Path(test_file).exists(), wf_res.get("result", ""))

    rf_res = await registry.execute("read_file", file_path=test_file)
    check("read_file()", "Jarvis Windows Automation" in rf_res.get("result", ""), rf_res.get("result", ""))

    ls_res = await registry.execute("list_directory", folder_path=test_dir)
    check("list_directory()", "test_note.txt" in ls_res.get("result", ""), ls_res.get("result", ""))

    sf_res = await registry.execute("search_files", query="test_note.txt", search_path=test_dir)
    check("search_files()", "test_note.txt" in sf_res.get("result", ""), sf_res.get("result", ""))

    del_res = await registry.execute("delete_file", file_path=test_file)
    check("delete_file()", not Path(test_file).exists(), del_res.get("result", ""))
    Path(test_dir).rmdir()

    # 5. Shell & Clipboard
    ps_res = await registry.execute("run_powershell", command="Get-Date -Format 'yyyy-MM-dd'")
    check("run_powershell()", ps_res.get("status") == "success", ps_res.get("result", ""))

    cb_set = await registry.execute("set_clipboard", text="Jarvis Clipboard Test 2026")
    check("set_clipboard()", cb_set.get("status") == "success", cb_set.get("result", ""))

    cb_get = await registry.execute("get_clipboard")
    check("get_clipboard()", "Jarvis Clipboard Test 2026" in cb_get.get("result", ""), cb_get.get("result", ""))

    # 6. GUI Hands & Desktop
    mm_res = await registry.execute("mouse_move", x=400, y=300)
    check("mouse_move(400, 300)", mm_res.get("status") == "success", mm_res.get("result", ""))

    kp_res = await registry.execute("keyboard_press", key="shift")
    check("keyboard_press('shift')", kp_res.get("status") == "success", kp_res.get("result", ""))

    sd_res = await registry.execute("show_desktop")
    check("show_desktop()", sd_res.get("status") == "success", sd_res.get("result", ""))

    # =========================================================================
    # PART 2: TRICKY PHRASING, ACCENTS & WEIRD SPACING INTENT TEST
    # =========================================================================
    print("\n--- [PART 2: TRICKY PHRASING, ACCENTS & SPACING REACTIVITY] ---")

    tricky_tests = [
        # 1. Volume variations
        ("Can you decrease the system volume?", "change_volume_relative"),
        ("make   it   louder   please", "change_volume_relative"),
        ("laptop's volume to 90", "set_volume"),
        ("turn the laptop volume to 75%", "set_volume"),
        ("mute the sound", "mute_volume"),
        ("unmute audio", "unmute_volume"),
        ("what is the volume", "get_volume"),

        # 2. Active Window & Context
        ("in which application I am currently.", "get_current_active_window"),
        ("what   app   am   i   using", "get_current_active_window"),
        ("where am i", "get_current_active_window"),

        # 3. Application Launch & Kill with slips
        ("Can you please open VSCOD?", "launch_application"),
        ("now try opening vs code", "launch_application"),
        ("open   blender   for   me", "launch_application"),
        ("close notepad", "kill_process"),
        ("terminate chrome", "kill_process"),

        # 4. Desktop & Power
        ("minimize all windows", "show_desktop"),
        ("show desktop", "show_desktop"),
        ("lock my pc", "lock_workstation"),

        # 5. Filesystem & Compound Commands
        ("can you open Viscode and create a demo folder in it?", "launch_application + create_directory"),
        ("Can you create a dummy folder in the root directory of vs code that I have opened?", "create_directory"),
        ("Create a dummy folder in VSAS code.", "create_directory"),
        ("create a folder called test_folder", "create_directory"),
        ("open explorer", "open_in_explorer"),
        ("find file settings.toml", "search_files"),

        # 6. YouTube & Browser Controls (Tab Reuse & New Tab)
        ("open minecraft videos on yt channel", "search_youtube"),
        ("i want to watch dream's channel", "search_youtube"),
        ("watch dream's channel in a new tab", "search_youtube"),

        # 7. Clipboard & Telemetry
        ("read clipboard", "get_clipboard"),
        ("what is on my clipboard", "get_clipboard"),
        ("gpu temp", "get_hardware_metrics"),
        ("what is my ip", "get_network_info"),
    ]

    for raw_input, expected_tool in tricky_tests:
        t0 = time.time()
        resp = await router.try_fast_path(raw_input)
        elapsed_ms = (time.time() - t0) * 1000

        matched = resp is not None
        check(
            f"Input: '{raw_input}'",
            matched,
            f"({elapsed_ms:.1f}ms) -> {resp[:60] if resp else 'NONE'}"
        )

    # Clean up any test folder created during test
    if Path("new_folder").exists():
        Path("new_folder").rmdir()
    if Path("test_folder").exists():
        Path("test_folder").rmdir()

    # =========================================================================
    # PART 3: LLM FALLBACK & TOOL CALLING REASONING TEST
    # =========================================================================
    print("\n--- [PART 3: LLM TOOL-CALLING REASONING WITH QWEN2.5-CODER] ---")
    llm = OllamaClient()
    healthy = await llm.check_health()
    if healthy:
        test_llm_queries = [
            "Please create a folder named demo_project for my new website.",
            "I need you to launch the visual studio code editor right away.",
            "Turn down the volume by 10 percent.",
        ]

        system_prompt = (
            "You are Jarvis, Om's British AI assistant.\n"
            + router.get_tool_prompt_section()
        )

        for q in test_llm_queries:
            t0 = time.time()
            buf = []
            async for tok in llm.stream(system_prompt=system_prompt, user_message=q):
                buf.append(tok)
            full_out = "".join(buf).strip()
            elapsed_s = time.time() - t0

            parsed = router.parse_tool_call(full_out)
            has_tool = parsed is not None
            tool_name = parsed[0] if parsed else "NONE"
            tool_args = parsed[1] if parsed else {}
            check(
                f"LLM Query: '{q}'",
                has_tool,
                f"({elapsed_s:.2f}s) Tool={tool_name}{tool_args} -> Raw: {full_out[:50]}"
            )
    else:
        print("  [SKIP] Ollama not available for Part 3.")

    print("\n=================================================================")
    print(f"   TEST SUMMARY: {passed} PASSED | {failed} FAILED")
    print("=================================================================")


if __name__ == "__main__":
    asyncio.run(run_windows_suite())
