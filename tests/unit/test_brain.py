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


def test_parse_agent_tool_call():
    d = parse_agent_decision('TOOL_CALL: set_volume({"percent": 80})')
    assert not d.is_final
    assert d.tool_name == "set_volume"
    assert d.tool_args == {"percent": 80}
