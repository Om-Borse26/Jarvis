"""Pure tests for the pluggable LLM provider (no network)."""
from jarvis.brain.llm_provider import OpenAICompatClient


def _client(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    return OpenAICompatClient("gemini")


def test_normalize_parses_openai_tool_calls():
    data = {"choices": [{"message": {
        "content": "",
        "tool_calls": [
            {"type": "function", "function": {"name": "set_volume", "arguments": '{"percent": 30}'}},
        ],
    }}]}
    out = OpenAICompatClient._normalize(data)
    assert out["tool_calls"] == [{"name": "set_volume", "arguments": {"percent": 30}}]
    assert out["content"] == ""


def test_normalize_plain_text_and_strips_think():
    data = {"choices": [{"message": {"content": "<think>hmm</think>Hello, Sir."}}]}
    out = OpenAICompatClient._normalize(data)
    assert out == {"content": "Hello, Sir.", "tool_calls": []}


def test_normalize_handles_bad_arguments():
    data = {"choices": [{"message": {"content": "",
            "tool_calls": [{"function": {"name": "x", "arguments": "not-json"}}]}}]}
    out = OpenAICompatClient._normalize(data)
    assert out["tool_calls"] == [{"name": "x", "arguments": {}}]


def test_sanitize_flattens_tool_and_toolcall_messages():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "do it"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"type": "function", "function": {"name": "open_dashboard", "arguments": {}}}]},
        {"role": "tool", "content": "done", "tool_name": "open_dashboard"},
    ]
    out = OpenAICompatClient._sanitize(messages)
    roles = [m["role"] for m in out]
    assert roles == ["system", "user", "assistant", "user"]
    assert "open_dashboard" in out[2]["content"]
    assert out[3]["content"].startswith("[result of open_dashboard]")


def test_route_model_returns_configured(monkeypatch):
    c = _client(monkeypatch)
    assert c.route_model("anything") == c._fast_model
