import asyncio
from unittest.mock import AsyncMock

import pytest

from jarvis.tools.process_control import decide_focus_message, _app_label
from jarvis.tools.router import ToolRouter, registry


# ── Pure focus-decision logic ────────────────────────────────────────────
@pytest.mark.parametrize(("label", "found", "is_fg", "expected"), [
    ("Brave", False, False, "Brave isn't open, Sir."),
    ("Brave", True, True, "You're already on Brave, Sir."),
    ("Brave", True, False, "Switched to Brave, Sir."),
    ("VS Code", True, False, "Switched to VS Code, Sir."),
])
def test_decide_focus_message(label, found, is_fg, expected):
    assert decide_focus_message(label, found=found, is_foreground=is_fg) == expected


@pytest.mark.parametrize(("query", "label"), [
    ("brave", "Brave"),
    ("vscode", "VS Code"),
    ("vs code", "VS Code"),
    ("notepad", "Notepad"),
    ("photoshop", "Photoshop"),
])
def test_app_label(query, label):
    assert _app_label(query) == label


# ── Router focus/switch fast-paths ───────────────────────────────────────
@pytest.mark.parametrize(("utterance", "app"), [
    ("switch to brave", "brave"),
    ("switch back to brave", "brave"),
    ("focus on vs code", "vs code"),
    ("focus brave", "brave"),
    ("show me brave", "brave"),
    ("bring up vs code", "vs code"),
    ("go to brave", "brave"),
    ("jarvis focus brave", "brave"),
])
def test_focus_fast_path_dispatches_focus_application(monkeypatch, utterance, app):
    execute = AsyncMock(return_value={"result": "Switched"})
    monkeypatch.setattr(registry, "execute", execute)
    assert asyncio.run(ToolRouter().try_fast_path(utterance)) == "Switched"
    execute.assert_awaited_once_with("focus_application", app_name=app)


def test_bare_focus_asks_which_app(monkeypatch):
    execute = AsyncMock()
    monkeypatch.setattr(registry, "execute", execute)
    result = asyncio.run(ToolRouter().try_fast_path("focus"))
    assert "which application" in result.lower()
    execute.assert_not_awaited()


def test_focus_does_not_hijack_media_or_tab_commands(monkeypatch):
    execute = AsyncMock()
    monkeypatch.setattr(registry, "execute", execute)
    # "switch to next tab" should not be treated as focusing an app called "next tab".
    for utterance in ("show me the next video", "switch to next tab"):
        execute.reset_mock()
        asyncio.run(ToolRouter().try_fast_path(utterance))
        for call in execute.await_args_list:
            assert call.args[0] != "focus_application"
