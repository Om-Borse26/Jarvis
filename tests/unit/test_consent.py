"""Consent gate: yes/no interpretation, descriptions, risk routing."""
from jarvis.security.consent import ConsentManager


def test_interpret_affirmatives():
    for w in ["yes", "yeah", "sure", "do it", "go ahead", "send it", "confirm"]:
        assert ConsentManager.interpret(w) is True, w


def test_interpret_negatives():
    for w in ["no", "nope", "cancel", "stop", "don't", "never mind"]:
        assert ConsentManager.interpret(w) is False, w


def test_interpret_ambiguous():
    assert ConsentManager.interpret("the weather is nice") is None
    assert ConsentManager.interpret("") is None


def test_requires_consent():
    assert ConsentManager.requires_consent("delete_directory") is True
    assert ConsentManager.requires_consent("get_volume") is False


def test_describe_includes_target():
    d = ConsentManager.describe("delete_directory", {"path": "demo"})
    assert "demo" in d
    assert "delete" in d.lower()


def test_timeout_clears_visual_confirmation():
    import asyncio
    from unittest.mock import Mock

    manager = ConsentManager(timeout=0.001)
    manager.clear_hud_fn = Mock()
    assert asyncio.run(manager.request("Disposable test")) is False
    manager.clear_hud_fn.assert_called_once_with()
    assert not manager.is_pending()
