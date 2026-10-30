import asyncio
from unittest.mock import AsyncMock

import pytest

from jarvis.ui.state import UIDirective
from jarvis.tools.router import ToolRouter, registry


# ── UI directive bridge ──────────────────────────────────────────────────
def test_directive_seq_increments_and_mode_set():
    d = UIDirective()
    s0 = d.snapshot()["seq"]
    d.set(mode="dashboard", forward=True)
    snap = d.snapshot()
    assert snap["mode"] == "dashboard"
    assert snap["forward"] is True
    assert snap["seq"] == s0 + 1


def test_directive_rejects_unknown_mode():
    d = UIDirective()
    d.set(mode="bogus")
    assert d.snapshot()["mode"] == "collapsed"


def test_directive_heartbeat_alive():
    d = UIDirective()
    assert d.is_alive() is False
    d.heartbeat()
    assert d.is_alive() is True


# ── Voice commands for the island ────────────────────────────────────────
@pytest.mark.parametrize(("utterance", "tool"), [
    ("come forward", "island_come_forward"),
    ("focus on yourself", "island_come_forward"),
    ("show yourself", "island_come_forward"),
    ("step back", "island_send_back"),
    ("minimize yourself", "island_send_back"),
    ("open dashboard", "open_dashboard"),
])
def test_island_voice_commands(monkeypatch, utterance, tool):
    execute = AsyncMock(return_value={"result": "ok"})
    monkeypatch.setattr(registry, "execute", execute)
    assert asyncio.run(ToolRouter().try_fast_path(utterance)) == "ok"
    execute.assert_awaited_once_with(tool)
