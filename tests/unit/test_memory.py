"""Memory layers: working (L2), episodic (L3), semantic (L4 keyword fallback)."""
from jarvis.memory.working import WorkingMemory
from jarvis.memory.episodic import EpisodicMemory
from jarvis.memory.semantic import SemanticMemory


def test_working_memory_snapshot():
    wm = WorkingMemory()
    wm.set_active_app("VS Code")
    wm.start_task("open the editor")
    wm.add_observation("launch_application", {"app_name": "vscode"}, "opened")
    snap = wm.context_snapshot()
    assert "VS Code" in snap
    assert "launch_application" in snap
    assert wm.recent_tools() == ["launch_application"]


def test_episodic_record_and_search(tmp_path):
    em = EpisodicMemory(db_path=tmp_path / "ep.db")
    em.record("deploy the app", ["git_push"], "done", True)
    em.record("play music", ["media_play_pause"], "done", True)
    hits = em.search("deploy")
    assert len(hits) == 1
    assert hits[0]["tools"] == ["git_push"]
    assert len(em.recent(5)) == 2


def test_semantic_keyword_recall(tmp_path):
    sm = SemanticMemory(db_path=tmp_path / "sem.db")
    sm.add("User prefers the Brave browser", "preference")
    sm.add("User works on the Jarvis project", "fact")
    hits = sm.recall("brave")
    assert any("Brave" in h for h in hits)
