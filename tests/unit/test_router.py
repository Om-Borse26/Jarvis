import asyncio
from unittest.mock import AsyncMock

import pytest

from jarvis.tools.router import ToolRouter, registry


@pytest.mark.parametrize("utterance", [
    "Did you open those Navratri videos on the browser?",
    "Delete the demo folder and also close the application",
    "Open VS Code and make a folder called demo in it",
])
def test_questions_and_compound_requests_do_not_execute_partial_actions(monkeypatch, utterance):
    execute = AsyncMock()
    monkeypatch.setattr(registry, "execute", execute)
    assert asyncio.run(ToolRouter().try_fast_path(utterance)) is None
    execute.assert_not_awaited()


def test_youtube_compound_query_excludes_instruction_words(monkeypatch):
    execute = AsyncMock(return_value={"result": "Opened"})
    monkeypatch.setattr(registry, "execute", execute)
    asyncio.run(ToolRouter().try_fast_path("Can you open youtube and search for some minecraft videos?"))
    execute.assert_awaited_once_with("search_youtube", query="minecraft videos")


@pytest.mark.parametrize(("utterance", "tool"), [
    ("Can you bring up the dashboard?", "open_dashboard"),
    ("Turn yourself off.", "stop_jarvis"),
    ("List MCP servers", "list_mcp_servers"),
])
def test_control_commands_dispatch_without_model(monkeypatch, utterance, tool):
    execute = AsyncMock(return_value={"result": "Done"})
    monkeypatch.setattr(registry, "execute", execute)
    assert asyncio.run(ToolRouter().try_fast_path(utterance)) == "Done"
    execute.assert_awaited_once_with(tool)