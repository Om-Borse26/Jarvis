import asyncio
from unittest.mock import AsyncMock

import pytest

from jarvis.memory.procedures import ProcedureMemory, normalize_name, split_steps
from jarvis.tools.router import ToolRouter, registry


@pytest.fixture
def fresh_procs(tmp_path, monkeypatch):
    monkeypatch.setattr(ProcedureMemory, "_instance", None)
    return ProcedureMemory(db_path=tmp_path / "procs.db")


# ── Name + step parsing ──────────────────────────────────────────────────
@pytest.mark.parametrize(("raw", "expected"), [
    ("my work routine", "work"),
    ("the Gaming Setup", "gaming setup"),
    ("morning procedure", "morning"),
])
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


def test_split_steps_variants():
    assert split_steps("open vs code, open brave, set volume to 30") == \
           ["open vs code", "open brave", "set volume to 30"]
    assert split_steps("open vs code and then open brave then mute") == \
           ["open vs code", "open brave", "mute"]
    assert split_steps(["open brave", "mute"]) == ["open brave", "mute"]


# ── Storage roundtrip ────────────────────────────────────────────────────
def test_save_get_delete_roundtrip(fresh_procs):
    assert fresh_procs.get("work") is None
    n = fresh_procs.save("my work routine", "open vs code, open brave")
    assert n == 2
    assert fresh_procs.get("work routine") == ["open vs code", "open brave"]
    assert "work" in fresh_procs.all_names()
    assert fresh_procs.delete("work") is True
    assert fresh_procs.get("work") is None


def test_save_rejects_empty(fresh_procs):
    assert fresh_procs.save("", "open brave") == 0
    assert fresh_procs.save("empty", "") == 0


# ── Router run fast-path ─────────────────────────────────────────────────
@pytest.mark.parametrize("utterance", [
    "run my work routine",
    "start my morning routine",
    "do my gaming setup",
])
def test_run_routine_fast_path(monkeypatch, utterance):
    execute = AsyncMock(return_value={"result": "Ran routine"})
    monkeypatch.setattr(registry, "execute", execute)
    assert asyncio.run(ToolRouter().try_fast_path(utterance)) == "Ran routine"
    assert execute.await_args.args[0] == "run_procedure"


def test_run_procedure_replays_steps(fresh_procs, monkeypatch):
    fresh_procs.save("work", "open brave, mute")
    from jarvis.tools import procedures as proc_tools
    # Point the tool module at the fresh test instance.
    monkeypatch.setattr(proc_tools, "procedure_memory", fresh_procs)

    calls = []

    async def fake_fast_path(step):
        calls.append(step)
        return f"did {step}"

    monkeypatch.setattr(ToolRouter, "try_fast_path", lambda self, s: fake_fast_path(s))
    result = asyncio.run(proc_tools.run_procedure("work"))
    assert calls == ["open brave", "mute"]
    assert "completed 2 of 2" in result
