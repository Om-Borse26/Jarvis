"""Scheduler: natural-language time parsing, CRUD, and missed-job relevance."""
import time

from jarvis.core.scheduler import parse_when, Scheduler


def test_parse_relative():
    p = parse_when("in 10 minutes")
    assert p["kind"] == "once"
    assert 590 < (p["fire_at"] - time.time()) < 610


def test_parse_recurring_every_hours():
    p = parse_when("every 2 hours")
    assert p["kind"] == "recurring"
    assert p["interval"] == 7200


def test_parse_every_morning():
    p = parse_when("every morning")
    assert p["kind"] == "recurring"
    assert p["interval"] == 86400


def test_parse_clock():
    p = parse_when("at 3pm")
    assert p["kind"] == "once"
    assert p["fire_at"] > time.time()


def test_parse_unparseable():
    assert parse_when("whenever you feel like it") is None


def test_crud(tmp_path):
    s = Scheduler(db_path=tmp_path / "sched.db")
    jid = s.add_job("once", "stretch", time.time() + 60, None)
    jobs = s.list_jobs()
    assert any(j["id"] == jid for j in jobs)
    assert s.cancel(jid) is True
    assert all(j["id"] != jid for j in s.list_jobs())


def test_missed_relevance():
    now = time.time()
    # normal missed → not relevant
    assert Scheduler._is_relevant("normal", now - 60, None, now) is False
    # critical within 24h → relevant
    assert Scheduler._is_relevant("critical", now - 3600, None, now) is True
    # meeting still upcoming → relevant; already past → not
    assert Scheduler._is_relevant("important", now - 60, now + 600, now) is True
    assert Scheduler._is_relevant("important", now - 600, now - 60, now) is False
