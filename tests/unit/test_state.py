"""State bridge: valid transitions, text capture, snapshot."""
from jarvis.ui.state import StateBridge


def test_set_and_snapshot():
    sb = StateBridge()
    sb.set("listening", "hello")
    snap = sb.snapshot()
    assert snap["state"] == "listening"
    assert snap["text"] == "hello"


def test_invalid_state_falls_back_to_idle():
    sb = StateBridge()
    sb.set("nonsense")
    assert sb.snapshot()["state"] == "idle"


def test_text_is_truncated():
    sb = StateBridge()
    sb.set_text("x" * 1000)
    assert len(sb.snapshot()["text"]) <= 300
