"""Personality wiring: config [jarvis].personality must shape the system prompt."""
from jarvis.core import arbiter
from jarvis.core.arbiter import _personality_guidance, PERSONALITY_STYLES


def test_known_personalities_map_to_distinct_styles():
    assert set(PERSONALITY_STYLES) == {"calm_professional", "witty", "formal", "casual"}
    assert len(set(PERSONALITY_STYLES.values())) == 4


def test_personality_guidance_reads_config(monkeypatch):
    monkeypatch.setattr(arbiter, "load_config",
                        lambda: {"jarvis": {"personality": "witty"}}, raising=False)
    # Patch the lazily-imported config loader used inside the function.
    import jarvis.core.config as cfg
    monkeypatch.setattr(cfg, "load_config", lambda: {"jarvis": {"personality": "witty"}})
    g = _personality_guidance()
    assert g == PERSONALITY_STYLES["witty"]


def test_personality_guidance_defaults_safely(monkeypatch):
    import jarvis.core.config as cfg
    monkeypatch.setattr(cfg, "load_config", lambda: {"jarvis": {}})
    assert _personality_guidance() == PERSONALITY_STYLES["calm_professional"]


def test_normal_prompt_has_persona_slot():
    assert "{personality}" in arbiter.NORMAL_SYSTEM_PROMPT
