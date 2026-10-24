"""Tool registry: native schema generation, type mapping, permission gate."""
import asyncio

from jarvis.tools.registry import ToolRegistry, register_tool, registry


def test_json_type_mapping():
    assert ToolRegistry._json_type("int") == "integer"
    assert ToolRegistry._json_type("float") == "number"
    assert ToolRegistry._json_type("bool") == "boolean"
    assert ToolRegistry._json_type("str") == "string"
    assert ToolRegistry._json_type("Optional[int]") == "integer"
    assert ToolRegistry._json_type("weirdtype") == "string"


def test_registered_tool_has_native_schema():
    @register_tool(name="unit_echo", description="Echo a value.", category="general")
    def unit_echo(value: str, times: int = 1) -> str:
        return value * times

    schema = {s["function"]["name"]: s for s in registry.get_tools_schema()}
    assert "unit_echo" in schema
    fn = schema["unit_echo"]["function"]
    assert fn["parameters"]["properties"]["value"]["type"] == "string"
    assert fn["parameters"]["properties"]["times"]["type"] == "integer"
    assert "value" in fn["parameters"]["required"]
    assert "times" not in fn["parameters"]["required"]


def test_execute_runs_tool():
    @register_tool(name="unit_add", description="Add.", category="general")
    def unit_add(a: int, b: int) -> str:
        return str(a + b)

    res = asyncio.run(registry.execute("unit_add", a=2, b=3))
    assert res["status"] == "success"
    assert res["result"] == "5"


def test_permission_gate_blocks(tmp_path, monkeypatch):
    from jarvis.core.permissions import permission_policy

    @register_tool(name="unit_blocked", description="x", category="code")
    def unit_blocked() -> str:
        return "ran"

    permission_policy.set("code", False)
    try:
        res = asyncio.run(registry.execute("unit_blocked"))
        assert res["status"] == "error"
        assert "not allowed" in res["message"].lower() or "turned off" in res["message"].lower()
    finally:
        permission_policy.set("code", True)


def test_execute_redacts_sensitive_arguments_in_application_log():
    from loguru import logger

    @register_tool(name="unit_secret_tool", description="Save a secret.", category="general")
    def unit_secret_tool(name: str, value: str, token: str) -> str:
        return f"saved {name}"

    captured_logs = []
    handler_id = logger.add(lambda msg: captured_logs.append(str(msg)), level="INFO")
    try:
        secret_val = "SUPER_SECRET_VALUE_99999"
        secret_tok = "SUPER_SECRET_TOKEN_88888"
        res = asyncio.run(registry.execute("unit_secret_tool", name="my_api", value=secret_val, token=secret_tok))
        assert res["status"] == "success"

        log_text = "".join(captured_logs)
        assert secret_val not in log_text, "Secret value leaked into application log!"
        assert secret_tok not in log_text, "Secret token leaked into application log!"
        assert "***REDACTED***" in log_text, "Expected redacted placeholder in application log"
    finally:
        logger.remove(handler_id)

