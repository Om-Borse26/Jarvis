"""Shared bus (Jarvis <-> Eve): event queue and shared key/value."""
from jarvis.memory.shared_bus import SharedBus


def test_push_pending_ack(tmp_path):
    bus = SharedBus(db_path=tmp_path / "shared.db")
    eid = bus.push_event("note", {"text": "buy milk"}, target="jarvis")
    pend = bus.pending("jarvis")
    assert len(pend) == 1
    assert pend[0]["payload"]["text"] == "buy milk"
    bus.ack(eid)
    assert bus.pending("jarvis") == []


def test_targets_are_isolated(tmp_path):
    bus = SharedBus(db_path=tmp_path / "shared.db")
    bus.push_event("task", {"text": "for eve"}, target="eve")
    assert bus.pending("jarvis") == []
    assert len(bus.pending("eve")) == 1


def test_kv(tmp_path):
    bus = SharedBus(db_path=tmp_path / "shared.db")
    assert bus.get_kv("name") is None
    bus.set_kv("name", "Om")
    assert bus.get_kv("name") == "Om"
