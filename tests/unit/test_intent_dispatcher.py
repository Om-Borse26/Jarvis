"""
Unit tests for Semantic Query Reformatter & Intent Dispatcher.
Verifies multi-intent decomposition, app shortcut resolution, anti-hallucination, and tier fallbacks.
"""
import pytest
from unittest.mock import patch, MagicMock

from jarvis.core.intent_dispatcher import IntentDispatcher, IntentResult
from jarvis.tools.registry import registry


@pytest.fixture
def dispatcher():
    return IntentDispatcher()


def test_parse_hotkey_from_text(dispatcher):
    text1 = "Use the keyboard shortcut Shift + Alt + F to format document."
    assert dispatcher._parse_hotkey_from_text(text1) == "shift+alt+f"

    text2 = "Press Ctrl + N to create a new file in Visual Studio Code."
    assert dispatcher._parse_hotkey_from_text(text2) == "ctrl+n"

    text3 = "No shortcut available."
    assert dispatcher._parse_hotkey_from_text(text3) is None


@pytest.mark.asyncio
async def test_resolve_app_action_tier2(dispatcher):
    # Built-in shortcut for vscode format document
    res = await dispatcher._resolve_app_action("vscode", "format document")
    assert res.intent_type == "tool_call"
    assert res.tool_calls == [{"name": "keyboard_hotkey", "arguments": {"hotkey": "shift+alt+f"}}]
    assert res.source == "rules_engine_shortcut"


@pytest.mark.asyncio
async def test_resolve_app_action_tier3_tavily(dispatcher):
    with patch("jarvis.core.intent_dispatcher._tavily_answer", return_value="In Figma on Windows, zoom to fit is Shift + 1"):
        res = await dispatcher._resolve_app_action("figma", "zoom to fit")
        assert res.intent_type == "tool_call"
        assert res.tool_calls == [{"name": "keyboard_hotkey", "arguments": {"hotkey": "shift+1"}}]
        assert res.source == "tavily_shortcut_search"


@pytest.mark.asyncio
async def test_resolve_app_action_tier4_unsupported(dispatcher):
    with patch("jarvis.core.intent_dispatcher._tavily_answer", return_value=""):
        res = await dispatcher._resolve_app_action("photoshop", "apply complex deep neural diffusion filter")
        assert res.intent_type == "unsupported"
        assert "custom tool would need to be created" in res.unsupported_reason
        assert res.source == "hierarchy_exhausted"


@pytest.mark.asyncio
async def test_dispatch_direct_tool_calls(dispatcher):
    mock_raw = {
        "intent_type": "tool_call",
        "tool_calls": [
            {"name": "set_volume", "arguments": {"volume": 80}},
            {"name": "set_brightness", "arguments": {"brightness": 50}},
        ]
    }
    with patch.object(dispatcher, "_call_reformatter", return_value=mock_raw):
        res = await dispatcher.dispatch("set volume to 80 and brightness to 50")
        assert res.intent_type == "tool_call"
        assert len(res.tool_calls) == 2
        assert res.tool_calls[0]["name"] == "set_volume"
        assert res.tool_calls[1]["name"] == "set_brightness"


@pytest.mark.asyncio
async def test_dispatch_unsupported_anti_hallucination(dispatcher):
    mock_raw = {
        "intent_type": "unsupported",
        "unsupported_reason": "I cannot physically cook breakfast."
    }
    with patch.object(dispatcher, "_call_reformatter", return_value=mock_raw):
        res = await dispatcher.dispatch("cook me breakfast")
        assert res.intent_type == "unsupported"
        assert res.unsupported_reason == "I cannot physically cook breakfast."
