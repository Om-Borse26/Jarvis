"""Regressions from the first real-PC test run (loops, small talk, YouTube, Island)."""
import asyncio
import py_compile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from jarvis.core.agent_loop import AgentLoop
from jarvis.core.intent_scope import is_smalltalk, select_tools
from jarvis.tools.registry import registry, ToolParameter
from jarvis.tools.router import ToolRouter

ROOT = Path(__file__).resolve().parents[2]


# ── Every module must at least compile (pipeline.py once shipped broken) ──
@pytest.mark.parametrize(
    "path", sorted(p for p in (ROOT / "jarvis").rglob("*.py")), ids=lambda p: str(p.relative_to(ROOT))
)
def test_module_compiles(path):
    py_compile.compile(str(path), doraise=True)


# ── Agent loop stop conditions ───────────────────────────────────────────
class _FakeLLM:
    """Always asks for the same tool call — like the weak model did."""

    def __init__(self, call):
        self.call = call
        self.calls = 0

    async def chat_with_tools(self, **_):
        self.calls += 1
        return {"content": "", "tool_calls": [self.call]}


@pytest.fixture
def echo_tool():
    registry.register(lambda text="": f"echo {text}", name="test_echo", description="echo", category="general")
    yield "test_echo"
    registry.unregister("test_echo")


@pytest.fixture
def failing_tool():
    def boom():
        raise RuntimeError("nope")
    registry.register(boom, name="test_boom", description="boom", category="general")
    yield "test_boom"
    registry.unregister("test_boom")


def test_single_intent_stops_after_first_success(echo_tool):
    llm = _FakeLLM({"name": echo_tool, "arguments": {"text": "x"}})
    out = asyncio.run(AgentLoop(llm).run(
        "say x", seed_tool_calls=[{"name": echo_tool, "arguments": {"text": "hi"}}], tools=[]))
    assert out == "echo hi"
    assert llm.calls == 0  # never went back to the model


def test_unknown_tool_stops_immediately():
    llm = _FakeLLM({"name": "browser_click", "arguments": {}})
    out = asyncio.run(AgentLoop(llm).run("click it", tools=[]))
    assert llm.calls == 1
    assert "step" not in out.lower()


def test_repeated_tool_is_cut_off(echo_tool):
    llm = _FakeLLM({"name": echo_tool, "arguments": {"text": "again"}})
    asyncio.run(AgentLoop(llm).run("do this and then that", tools=[]))
    assert llm.calls <= AgentLoop.MAX_SAME_TOOL + 1


def test_consecutive_failures_stop(failing_tool):
    llm = _FakeLLM({"name": failing_tool, "arguments": {}})
    out = asyncio.run(AgentLoop(llm).run("do this and then that", tools=[]))
    assert llm.calls == AgentLoop.MAX_CONSECUTIVE_ERRORS
    assert out.startswith("I couldn't get that done")


def test_no_step_by_step_narration(echo_tool):
    llm = _FakeLLM({"name": echo_tool, "arguments": {"text": "x"}})
    out = asyncio.run(AgentLoop(llm).run("do a and then b", tools=[]))
    assert "Step 1" not in out and "Here's what I accomplished" not in out


# ── Small talk / tool selection ──────────────────────────────────────────
@pytest.mark.parametrize("utterance", [
    "How are you?", "hello jarvis", "thank you", "good morning", "who are you",
    "what's up", "tell me a joke", "I'm tired", "okay", "bye",
])
def test_smalltalk_gets_no_tools(utterance):
    assert is_smalltalk(utterance)
    tools, _ = select_tools(utterance)
    assert tools == []


@pytest.mark.parametrize("utterance", ["open brave", "set volume to 30", "create a folder called x"])
def test_commands_are_not_smalltalk(utterance):
    assert not is_smalltalk(utterance)
    tools, _ = select_tools(utterance)
    assert tools


def test_plain_question_without_scope_gets_no_tools():
    tools, _ = select_tools("why is the sky blue")
    assert tools == []


@pytest.fixture
def fake_mcp_tools():
    async def _noop(**_):
        return "ok"
    registry.register_external("playwright_browser_click", "click", "mcp:playwright",
                               [ToolParameter("target", "string", "t")], _noop)
    registry.register_external("playwright_browser_run_code_unsafe", "run", "mcp:playwright", [], _noop)
    yield
    registry.unregister("playwright_browser_click")
    registry.unregister("playwright_browser_run_code_unsafe")


def test_external_mcp_tools_excluded_by_default(fake_mcp_tools):
    names = {s["function"]["name"] for s in registry.get_tools_schema()}
    assert "playwright_browser_click" not in names
    names = {s["function"]["name"] for s in registry.get_tools_schema(["web"])}
    assert "playwright_browser_click" not in names


def test_external_mcp_tools_opt_in_but_never_unsafe(fake_mcp_tools):
    names = {s["function"]["name"] for s in registry.get_tools_schema(["mcp"])}
    assert "playwright_browser_click" in names
    assert "playwright_browser_run_code_unsafe" not in names


def test_playwright_mention_opts_in(fake_mcp_tools):
    tools, scoped = select_tools("use playwright to click the login button")
    assert "mcp" in scoped
    assert "playwright_browser_click" in {s["function"]["name"] for s in tools}


# ── YouTube phrasing variants hit the fast path ──────────────────────────
@pytest.mark.parametrize("utterance", [
    "Open YouTube.", "Can you open YouTube?", "open youtube for me",
    "please open youtube", "go to youtube", "open youtube in brave",
])
def test_open_youtube_fast_path(monkeypatch, utterance):
    execute = AsyncMock(return_value={"result": "ok"})
    monkeypatch.setattr(registry, "execute", execute)
    assert asyncio.run(ToolRouter().try_fast_path(utterance)) == "Opening YouTube, Sir."
    assert execute.await_args.args[0] == "open_website"


# ── Brightness vs volume routing (brightness must not hit volume) ────────
@pytest.mark.parametrize(("utterance", "tool"), [
    ("set brightness to 80", "set_brightness"),
    ("set volume to 40", "set_volume"),
    ("increase brightness", "change_brightness_relative"),
    ("dim the screen", "change_brightness_relative"),
    ("whats the brightness", "get_brightness"),
    ("volume up", "change_volume_relative"),
])
def test_brightness_and_volume_routing(monkeypatch, utterance, tool):
    execute = AsyncMock(return_value={"result": "ok"})
    monkeypatch.setattr(registry, "execute", execute)
    asyncio.run(ToolRouter().try_fast_path(utterance))
    assert execute.await_args_list[0].args[0] == tool


# ── Island bridge must stay freeze-safe ──────────────────────────────────
def test_island_api_has_no_public_attributes():
    from jarvis.ui.island import IslandApi
    api = IslandApi(worker=type("W", (), {"submit": lambda *a: None})())
    public_attrs = [k for k in vars(api) if not k.startswith("_")]
    assert public_attrs == []


def test_island_api_methods_return_immediately():
    from jarvis.ui.island import IslandApi
    submitted = []
    api = IslandApi(worker=type("W", (), {"submit": lambda self, k, v: submitted.append((k, v))})())
    assert api.set_mode("mini") is True
    assert api.set_mode("bogus") is True
    assert api.come_forward() is True
    assert submitted == [("mode", "mini"), ("z", "front")]


def test_island_geometry_centered_and_scaled():
    from jarvis.ui.island import compute_geometry
    x, y, w, h, r = compute_geometry("collapsed", 1920, 1080, 1.0)
    assert (w, h) == (380, 54) and x == (1920 - 380) // 2 and y == 12
    x, y, w, h, r = compute_geometry("collapsed", 2400, 1350, 1.25)
    assert (w, h) == (475, 67)
    _, _, w, h, _ = compute_geometry("dashboard", 1280, 720, 1.0)
    assert w <= 1280 and h <= 720


# ── Parameter alias adaptors in registry.execute ────────────────────────
def test_adapt_kwargs_aliases():
    from jarvis.tools.registry import registry
    def dummy_vol(percent: int = 50): pass
    adapted = registry._adapt_kwargs(dummy_vol, "set_volume", {"volume": 50})
    assert adapted == {"percent": 50}

    def dummy_rem(text: str = "", when: str = ""): pass
    adapted_rem = registry._adapt_kwargs(dummy_rem, "set_reminder", {"reminder": "stretch", "when": "in 1 minute"})
    assert adapted_rem == {"text": "stretch", "when": "in 1 minute"}

    def dummy_win(title_keyword: str = ""): pass
    adapted_win = registry._adapt_kwargs(dummy_win, "focus_window", {"name": "Brave"})
    assert adapted_win == {"title_keyword": "Brave"}


# ── Full screen routing and screen OCR pattern exclusions ───────────────
def test_full_screen_routing(monkeypatch):
    execute = AsyncMock(return_value={"result": "ok"})
    monkeypatch.setattr(registry, "execute", execute)
    result = asyncio.run(ToolRouter().try_fast_path("make brave full screen"))
    assert result is not None
    assert execute.await_args_list[0].args[0] == "focus_application"
    assert execute.await_args_list[1].args[0] == "keyboard_hotkey"
    assert execute.await_args_list[1].kwargs == {"hotkey": "f11"}


def test_youtube_video_intent_routing(monkeypatch):
    execute = AsyncMock(return_value={"result": "ok"})
    monkeypatch.setattr(registry, "execute", execute)
    result = asyncio.run(ToolRouter().try_fast_path("open some valorant videos"))
    assert result is not None
    assert execute.await_args_list[0].args[0] == "play_youtube_video"
    assert execute.await_args_list[0].kwargs["query"] == "valorant videos"


def test_screen_ocr_pattern_excludes_fullscreen_and_brightness():
    from jarvis.core.pipeline import SCREEN_CAPTURE_PAT
    assert SCREEN_CAPTURE_PAT.search("make brave full screen") is None
    assert SCREEN_CAPTURE_PAT.search("turn down screen brightness") is None
    assert SCREEN_CAPTURE_PAT.search("lock screen") is None
    assert SCREEN_CAPTURE_PAT.search("what is on my screen right now") is not None

