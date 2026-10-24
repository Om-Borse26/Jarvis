"""Permission policy: default allow, user toggles, and MCP base-category mapping."""
import importlib

from jarvis.core.permissions import PermissionPolicy


def _fresh(tmp_path):
    p = tmp_path / "permissions.json"
    return PermissionPolicy(path=p)


def test_default_allows_everything(tmp_path):
    pol = _fresh(tmp_path)
    assert pol.is_allowed("code") is True
    assert pol.is_allowed("computer_use") is True


def test_disable_blocks_category(tmp_path):
    pol = _fresh(tmp_path)
    pol.set("code", False)
    assert pol.is_allowed("code") is False
    # persisted
    reloaded = PermissionPolicy(path=pol.path)
    assert reloaded.is_allowed("code") is False


def test_mcp_subcategory_maps_to_base(tmp_path):
    pol = _fresh(tmp_path)
    pol.set("mcp", False)
    assert pol.is_allowed("mcp:playwright") is False
    assert pol.is_allowed("mcp:tavily") is False


def test_unknown_category_defaults_allow(tmp_path):
    pol = _fresh(tmp_path)
    assert pol.is_allowed("something_new") is True
