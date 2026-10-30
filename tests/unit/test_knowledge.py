import asyncio
from unittest.mock import AsyncMock

import pytest

from jarvis.memory.facts import FactMemory, _normalize
from jarvis.tools.knowledge import looks_private, _concise
from jarvis.tools.router import ToolRouter, registry


# ── Concise web-answer cleaner ───────────────────────────────────────────
def test_concise_strips_source_citations():
    verbose = ('The capital of France is Paris, as stated in the source from '
               'Facebook: "The capital of France __ Paris (is/are)." The other '
               'source on Quora does not provide information about the capital of France.')
    out = _concise(verbose)
    assert out == "The capital of France is Paris."
    assert "source" not in out.lower() and "facebook" not in out.lower()


def test_concise_keeps_clean_answer_but_caps_length():
    clean = ("Pride and Prejudice is a novel by English author Jane Austen. "
             "Written when she was aged 20-21, it was her third novel.")
    out = _concise(clean, max_chars=240)
    assert out.startswith("Pride and Prejudice is a novel by English author Jane Austen.")
    assert len(out) <= 240


def test_concise_handles_empty():
    assert _concise("") == ""



# ── Fact memory ──────────────────────────────────────────────────────────
@pytest.fixture
def fresh_facts(tmp_path, monkeypatch):
    monkeypatch.setattr(FactMemory, "_instance", None)
    return FactMemory(db_path=tmp_path / "facts.db")


def test_normalize_collapses_phrasing():
    assert _normalize("Hey Jarvis, what's the Capital of France?") == \
           _normalize("what is the capital of france")


def test_remember_and_recall_roundtrip(fresh_facts):
    assert fresh_facts.recall("what is the capital of france") is None
    fresh_facts.remember("What is the capital of France?", "Paris.", source="tavily")
    assert fresh_facts.recall("what's the capital of france") == "Paris."
    assert fresh_facts.count() == 1


def test_remember_updates_existing(fresh_facts):
    fresh_facts.remember("who is the president", "Person A")
    fresh_facts.remember("who is the president", "Person B")
    assert fresh_facts.recall("who is the president") == "Person B"
    assert fresh_facts.count() == 1


def test_remember_rejects_empty(fresh_facts):
    assert fresh_facts.remember("", "x") is False
    assert fresh_facts.remember("q", "   ") is False


# ── Privacy guard ────────────────────────────────────────────────────────
@pytest.mark.parametrize("q", [
    "what's in my file report.docx",
    "what is on my screen",
    "read my passwords",
    "what does this code do",
    "summarize C:\\\\Users\\\\me\\\\notes.txt",
])
def test_private_questions_flagged(q):
    assert looks_private(q) is True


@pytest.mark.parametrize("q", [
    "what is the capital of france",
    "who won the world cup",
    "how tall is mount everest",
])
def test_public_questions_not_flagged(q):
    assert looks_private(q) is False


# ── Router knowledge routing ─────────────────────────────────────────────
@pytest.mark.parametrize("utterance", [
    "what is the capital of France",
    "who won the match yesterday",
    "how far is the moon",
])
def test_knowledge_questions_route_to_answer_from_web(monkeypatch, utterance):
    execute = AsyncMock(return_value={"result": "Answer"})
    monkeypatch.setattr(registry, "execute", execute)
    assert asyncio.run(ToolRouter().try_fast_path(utterance)) == "Answer"
    execute.assert_awaited_once()
    assert execute.await_args.args[0] == "answer_from_web"


@pytest.mark.parametrize("utterance", [
    "what's on my screen",
    "what can you do",
    "what is my name",
    "what's the volume",
])
def test_pc_and_self_questions_do_not_hit_web(monkeypatch, utterance):
    execute = AsyncMock(return_value={"result": "x"})
    monkeypatch.setattr(registry, "execute", execute)
    asyncio.run(ToolRouter().try_fast_path(utterance))
    for call in execute.await_args_list:
        assert call.args[0] != "answer_from_web"
