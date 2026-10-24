"""Audit log: secret redaction and risk classification."""
from jarvis.security.audit import classify_risk, redact, HIGH_RISK_TOOLS


def test_classify_risk():
    assert classify_risk("execute_shell") == "high"
    assert classify_risk("delete_directory") == "high"
    assert classify_risk("get_volume") == "normal"


def test_redact_masks_secret_keys():
    out = redact({"name": "github", "value": "supersecret", "password": "p@ss", "token": "abc"})
    assert out["name"] == "github"
    assert out["value"] == "***REDACTED***"
    assert out["password"] == "***REDACTED***"
    assert out["token"] == "***REDACTED***"


def test_redact_truncates_long_values():
    out = redact({"content": "a" * 500})
    assert len(out["content"]) <= 301


def test_high_risk_set_sane():
    assert "git_push" in HIGH_RISK_TOOLS
    assert "import_credentials" in HIGH_RISK_TOOLS
    assert "get_volume" not in HIGH_RISK_TOOLS
