"""Brain + agent parsing: native tool-call normalization and legacy fallback."""
from jarvis.brain.ollama_client import OllamaClient
from jarvis.core.agent_loop import parse_agent_decision


def test_normalize_tool_calls_from_dict():
    resp = {"message": {"content": "", "tool_calls": [
        {"function": {"name": "set_volume", "arguments": {"percent": 50}}}
    ]}}
    out = OllamaClient._normalize_tool_response(resp)
    assert out["tool_calls"][0]["name"] == "set_volume"
    assert out["tool_calls"][0]["arguments"] == {"percent": 50}


def test_normalize_string_arguments():
    resp = {"message": {"tool_calls": [
        {"function": {"name": "f", "arguments": '{"x": 1}'}}
    ]}}
    out = OllamaClient._normalize_tool_response(resp)
    assert out["tool_calls"][0]["arguments"] == {"x": 1}


def test_normalize_strips_think_tags():
    resp = {"message": {"content": "<think>hmm</think>Hello there."}}
    out = OllamaClient._normalize_tool_response(resp)
    assert out["content"] == "Hello there."
    assert out["tool_calls"] == []


def test_parse_agent_final():
    d = parse_agent_decision("FINAL_RESPONSE: All done, Sir.")
    assert d.is_final
    assert "done" in d.response_text.lower()


def test_normalize_text_json_tool_call():
    result = OllamaClient._normalize_tool_response({"message": {
        "content": '{"name":"open_dashboard","arguments":{}}'
    }})
    assert result == {"content": "", "tool_calls": [{"name": "open_dashboard", "arguments": {}}]}


def test_normalize_fenced_tool_call():
    result = OllamaClient._normalize_tool_response({"message": {
        "content": '```json\n{"function":{"name":"set_reminder","arguments":{"text":"stretch","when":"in 1 minute"}}}\n```'
    }})
    assert result["content"] == ""
    assert result["tool_calls"][0]["name"] == "set_reminder"


def test_malformed_text_call_is_not_spoken_or_executed():
    result = OllamaClient._normalize_tool_response({"message": {
        "content": '{"name":"execute_shell","arguments":'
    }})
    assert result["tool_calls"] == []
    assert "rephrase" in result["content"]


def test_parse_agent_tool_call():
    d = parse_agent_decision('TOOL_CALL: set_volume({"percent": 80})')
    assert not d.is_final
    assert d.tool_name == "set_volume"
    assert d.tool_args == {"percent": 80}


def test_agent_executes_all_seeded_calls_and_observes_results(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from jarvis.core.agent_loop import AgentLoop, registry

    execute = AsyncMock(side_effect=[
        {"status": "success", "result": "Opening your dashboard."},
        {"status": "success", "result": "Servers: playwright."},
    ])
    monkeypatch.setattr(registry, "execute", execute)
    llm = SimpleNamespace(chat_with_tools=AsyncMock(return_value={
        "content": "Both tasks are complete.", "tool_calls": []
    }))
    result = asyncio.run(AgentLoop(llm).run("two tasks", seed_tool_calls=[
        {"name": "open_dashboard", "arguments": {}},
        {"name": "list_mcp_servers", "arguments": {}},
    ]))
    assert [call.args[0] for call in execute.await_args_list] == ["open_dashboard", "list_mcp_servers"]
    # Both results are reported, without an extra round-trip to the model.
    assert result == "Opening your dashboard. Servers: playwright."
    llm.chat_with_tools.assert_not_awaited()


def test_text_call_reaches_agent_execution(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from jarvis.core.agent_loop import AgentLoop, registry

    decision = OllamaClient._normalize_tool_response({"message": {
        "content": '{"name":"open_dashboard","arguments":{}}'
    }})
    execute = AsyncMock(return_value={"status": "success", "result": "Opening your dashboard."})
    monkeypatch.setattr(registry, "execute", execute)
    llm = SimpleNamespace(chat_with_tools=AsyncMock(return_value={"content": "Opened.", "tool_calls": []}))
    asyncio.run(AgentLoop(llm).run("open dashboard", seed_tool_calls=decision["tool_calls"]))
    execute.assert_awaited_once_with("open_dashboard")
