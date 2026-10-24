"""
Wiring smoke test: the full tool-registration chain imports without error and
every registered tool produces a valid native function-calling schema.
"""
import jarvis.tools  # noqa: F401  (triggers registration of all tools)
from jarvis.tools.registry import registry


CRITICAL_TOOLS = {
    # native fast-path / OS
    "set_volume", "launch_application", "kill_process", "lock_workstation",
    # computer use + visual grounding
    "screenshot", "click_text", "label_screen_elements", "click_labeled_element",
    # code
    "execute_shell", "execute_python", "write_code_to_file",
    # security
    "save_secret", "import_credentials", "autofill_login", "find_login",
    # memory
    "save_user_memory", "recall_user_memories", "recall_past_actions",
    # scheduler
    "set_reminder", "schedule_meeting", "list_reminders", "cancel_reminder",
    # lifecycle / ui
    "stop_jarvis", "enable_startup", "open_dashboard",
    # mcp + eve
    "connect_mcp_server", "list_mcp_tools", "note_for_eve", "check_eve_updates",
}


def test_critical_tools_registered():
    names = {t.name for t in registry.list_tools()}
    missing = CRITICAL_TOOLS - names
    assert not missing, f"missing tools: {sorted(missing)}"


def test_every_tool_has_valid_native_schema():
    schemas = registry.get_tools_schema()
    assert len(schemas) >= 50
    for s in schemas:
        assert s["type"] == "function"
        fn = s["function"]
        assert fn["name"]
        assert fn["parameters"]["type"] == "object"
        for pname, pdef in fn["parameters"]["properties"].items():
            assert pdef["type"] in {"string", "integer", "number", "boolean", "array", "object"}


def test_no_duplicate_tool_names():
    names = [t.name for t in registry.list_tools()]
    assert len(names) == len(set(names)), "duplicate tool names registered"
