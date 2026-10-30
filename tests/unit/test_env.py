import os

from jarvis.core import env as env_mod


def _reset():
    env_mod._LOADED = False


def test_load_env_parses_and_does_not_override(tmp_path, monkeypatch):
    _reset()
    envfile = tmp_path / ".env"
    envfile.write_text(
        "# a comment\n"
        'TAVILY_API_KEY="tvly-abc123"\n'
        "EMPTY=\n"
        "ALREADY_SET=fromfile\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("ALREADY_SET", "fromenv")

    env_mod.load_env_file(envfile)

    assert os.environ["TAVILY_API_KEY"] == "tvly-abc123"
    assert os.environ.get("EMPTY") == ""
    # Real environment wins over the file.
    assert os.environ["ALREADY_SET"] == "fromenv"
    _reset()


def test_load_env_missing_file_is_safe(tmp_path):
    _reset()
    env_mod.load_env_file(tmp_path / "nope.env")  # should not raise
    _reset()
