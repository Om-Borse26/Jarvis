"""Config loads and contains every section the app relies on."""
from jarvis.core.config import load_config


def test_required_sections_present():
    cfg = load_config()
    for section in ("jarvis", "audio", "wake_word", "hotkey", "stt", "tts",
                    "llm", "memory", "vault", "mcp", "ui", "eve"):
        assert section in cfg, f"missing [{section}] in settings.toml"


def test_llm_routing_keys():
    cfg = load_config()
    assert "routing" in cfg["llm"]
    for k in ("code_keywords", "deep_keywords", "long_context_trigger"):
        assert k in cfg["llm"]["routing"]


def test_ui_and_eve_ports():
    cfg = load_config()
    assert isinstance(cfg["ui"]["http_port"], int)
    assert isinstance(cfg["eve"]["port"], int)
    assert cfg["ui"]["http_port"] != cfg["eve"]["port"]
