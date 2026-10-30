"""Pure tests for the CDP browser helpers (no live browser)."""
import pytest

from jarvis.tools.cdp_browser import CDPBrowser


@pytest.fixture
def br():
    b = CDPBrowser()
    b._order = []
    b._current = None
    return b


@pytest.mark.parametrize(("raw", "expected"), [
    ("example.com", "https://example.com"),
    ("https://a.com", "https://a.com"),
    ("http://a.com", "http://a.com"),
    ("about:blank", "about:blank"),
    ("data:text/html,<p>hi</p>", "data:text/html,<p>hi</p>"),
    ("file:///c:/x.html", "file:///c:/x.html"),
    ("", "about:blank"),
])
def test_norm_url(raw, expected):
    assert CDPBrowser._norm_url(raw) == expected


def test_stable_tab_order_survives_reordering(br, monkeypatch):
    # Chrome's /json reorders on activate; our _pages() must keep creation order.
    pages = [{"id": "A", "type": "page"}, {"id": "B", "type": "page"}, {"id": "C", "type": "page"}]
    monkeypatch.setattr(br, "_pages_raw", lambda: pages)
    assert [p["id"] for p in br._pages()] == ["A", "B", "C"]

    # Simulate activation reordering the raw list — order must be preserved.
    pages.reverse()
    assert [p["id"] for p in br._pages()] == ["A", "B", "C"]


def test_closed_tabs_drop_and_new_tabs_append(br, monkeypatch):
    state = {"pages": [{"id": "A", "type": "page"}, {"id": "B", "type": "page"}]}
    monkeypatch.setattr(br, "_pages_raw", lambda: state["pages"])
    br._pages()  # seed order A,B
    state["pages"] = [{"id": "B", "type": "page"}, {"id": "C", "type": "page"}]  # A closed, C new
    assert [p["id"] for p in br._pages()] == ["B", "C"]


def test_page_at_uses_stable_index(br, monkeypatch):
    pages = [{"id": "A", "type": "page"}, {"id": "B", "type": "page"}]
    monkeypatch.setattr(br, "_pages_raw", lambda: pages)
    assert br._page_at(1)["id"] == "B"
    assert br._page_at(5) is None
