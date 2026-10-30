"""
J.A.R.V.I.S. — CDP Browser (dedicated, fully controllable)

Chromium 136+ blocks --remote-debugging-port on your DEFAULT profile for
security, so Jarvis cannot attach CDP to your normal logged-in Brave. The
workaround: launch a SEPARATE browser profile with remote debugging enabled —
"Jarvis's browser" — and drive it over the DevTools Protocol. Your real browser
is never touched by CDP (that still uses keyboard automation).

This gives full freedom on the dedicated browser: open/navigate, real per-tab
focus (switch to a specific tab), close tabs, run JS, and autofill login forms
by locating the fields in the DOM (no manual clicking).

Transport is raw CDP: HTTP /json endpoints for tab lifecycle + a short-lived
websocket per command for Page.navigate / Runtime.evaluate. Tools are sync, so
the registry runs them off the event loop.
"""
from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Optional

from loguru import logger

from jarvis.tools.registry import register_tool


def _cfg():
    try:
        from jarvis.core.config import load_config
        return load_config().get("browser", {})
    except Exception:
        return {}


_BRAVE_PATHS = [
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
]
_CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def _resolve_exe(pref: str = "auto") -> Optional[str]:
    import os
    c = _cfg()
    cfg_brave = c.get("brave_path", "")
    cfg_chrome = c.get("chrome_path", "")
    local = os.environ.get("LOCALAPPDATA", "")
    brave = ([cfg_brave] if cfg_brave else []) + _BRAVE_PATHS + [rf"{local}\BraveSoftware\Brave-Browser\Application\brave.exe"]
    chrome = ([cfg_chrome] if cfg_chrome else []) + _CHROME_PATHS + [rf"{local}\Google\Chrome\Application\chrome.exe"]
    order = {"brave": [brave], "chrome": [chrome]}.get(pref, [brave, chrome])
    for group in order:
        for p in group:
            if p and Path(p).exists():
                return p
    return None


class CDPBrowser:
    """Singleton manager for the dedicated CDP-controlled browser."""

    _instance: Optional["CDPBrowser"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        c = _cfg()
        self.port = int(c.get("cdp_port", 9222))
        self.pref = str(c.get("cdp_browser", "auto")).lower()
        self.profile = Path(c.get("cdp_profile", "data/browser_profile")).resolve()
        self._proc = None
        self._current: Optional[str] = None   # last-used target id
        self._order: list[str] = []           # stable tab order (creation order)

    @property
    def _base(self) -> str:
        return f"http://localhost:{self.port}"

    def _get(self, path: str, method: str = "GET"):
        req = urllib.request.Request(f"{self._base}{path}", method=method)
        with urllib.request.urlopen(req, timeout=5) as r:
            body = r.read().decode("utf-8")
            return json.loads(body) if body.strip().startswith(("{", "[")) else body

    def _version(self):
        try:
            return self._get("/json/version")
        except Exception:
            return None

    def ensure(self) -> bool:
        """Launch the dedicated browser with remote debugging if not already up."""
        if self._version():
            return True
        exe = _resolve_exe(self.pref)
        if not exe:
            raise RuntimeError("No Brave or Chrome installation found for the CDP browser.")
        self.profile.mkdir(parents=True, exist_ok=True)
        args = [
            exe,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.profile}",
            "--remote-allow-origins=*",
            "--no-first-run",
            "--no-default-browser-check",
            "--restore-last-session=false",
            "about:blank",
        ]
        logger.info(f"[CDP] Launching dedicated browser: {Path(exe).name} on port {self.port}")
        self._proc = subprocess.Popen(args)
        for _ in range(40):
            if self._version():
                return True
            time.sleep(0.5)
        return False

    # ── tab lifecycle (HTTP) ─────────────────────────────────────────────
    def _pages_raw(self) -> list[dict]:
        data = self._get("/json")
        return [t for t in data if t.get("type") == "page"]

    def _pages(self) -> list[dict]:
        """Pages in a STABLE creation order (Chrome's /json reorders on activate)."""
        raw = {t["id"]: t for t in self._pages_raw()}
        self._order = [i for i in self._order if i in raw]   # drop closed
        for i in raw:                                        # append newly seen
            if i not in self._order:
                self._order.append(i)
        return [raw[i] for i in self._order]

    def list_tabs(self) -> list[dict]:
        return [{"index": i, "title": t.get("title", ""), "url": t.get("url", "")}
                for i, t in enumerate(self._pages())]

    def _page_at(self, index: int) -> Optional[dict]:
        pages = self._pages()
        return pages[index] if 0 <= index < len(pages) else None

    def _current_page(self) -> Optional[dict]:
        pages = self._pages()
        if self._current:
            for t in pages:
                if t["id"] == self._current:
                    return t
        return pages[0] if pages else None

    @staticmethod
    def _norm_url(url: str) -> str:
        u = (url or "").strip()
        if not u:
            return "about:blank"
        if not u.startswith(("http://", "https://", "about:", "chrome:", "file:", "data:")):
            u = "https://" + u
        return u

    def new_tab(self, url: str = "") -> dict:
        # Create a blank tab, then navigate via CDP so any URL (incl. data:) works.
        t = self._get("/json/new", method="PUT")
        self._current = t.get("id")
        if url:
            try:
                self._ws_cmd(t["webSocketDebuggerUrl"], "Page.navigate", {"url": self._norm_url(url)})
            except Exception as e:
                logger.debug(f"[CDP] new_tab navigate notice: {e}")
        return t

    def activate(self, index: int) -> Optional[dict]:
        t = self._page_at(index)
        if not t:
            return None
        self._get(f"/json/activate/{t['id']}")
        self._current = t["id"]
        return t

    def close(self, index: int) -> bool:
        t = self._page_at(index)
        if not t:
            return False
        self._get(f"/json/close/{t['id']}")
        return True

    # ── CDP commands (websocket) ─────────────────────────────────────────
    def _ws_cmd(self, ws_url: str, method: str, params: Optional[dict] = None):
        import websocket
        ws = websocket.create_connection(ws_url, timeout=15,
                                         suppress_origin=True)
        try:
            ws.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
            while True:
                msg = json.loads(ws.recv())
                if msg.get("id") == 1:
                    return msg
        finally:
            ws.close()

    def navigate(self, url: str) -> str:
        t = self._current_page() or self.new_tab()
        u = self._norm_url(url)
        self._ws_cmd(t["webSocketDebuggerUrl"], "Page.navigate", {"url": u})
        self._current = t["id"]
        return u

    def evaluate(self, expression: str):
        t = self._current_page()
        if not t:
            return None
        res = self._ws_cmd(t["webSocketDebuggerUrl"], "Runtime.evaluate",
                           {"expression": expression, "returnByValue": True})
        return (((res or {}).get("result") or {}).get("result") or {}).get("value")


cdp = CDPBrowser()


# ─── Tools ────────────────────────────────────────────────────────────────

@register_tool(
    name="cdp_open_browser",
    description="Open Jarvis's own dedicated, fully controllable browser (separate from your main Brave) and optionally navigate to a URL. Use this when you want Jarvis to control tabs, read pages, or fill forms programmatically.",
    category="web",
)
def cdp_open_browser(url: str = "") -> str:
    if not cdp.ensure():
        return "I couldn't start the dedicated browser, Sir."
    if url:
        cdp.navigate(url)
        return f"Opened my browser at {cdp._norm_url(url)}, Sir."
    return "My dedicated browser is open, Sir."


@register_tool(
    name="cdp_navigate",
    description="Navigate the active tab of Jarvis's dedicated browser to a URL.",
    category="web",
)
def cdp_navigate(url: str) -> str:
    cdp.ensure()
    return f"Navigating to {cdp.navigate(url)}, Sir."


@register_tool(
    name="cdp_new_tab",
    description="Open a new tab in Jarvis's dedicated browser, optionally at a URL.",
    category="web",
)
def cdp_new_tab(url: str = "") -> str:
    cdp.ensure()
    cdp.new_tab(url)
    return f"Opened a new tab{(' at ' + cdp._norm_url(url)) if url else ''}, Sir."


@register_tool(
    name="cdp_list_tabs",
    description="List the open tabs (index, title, URL) in Jarvis's dedicated browser.",
    category="web",
)
def cdp_list_tabs() -> str:
    cdp.ensure()
    tabs = cdp.list_tabs()
    if not tabs:
        return "No tabs are open in my browser, Sir."
    lines = [f"{t['index']}: {t['title'] or t['url']}" for t in tabs]
    return "Open tabs — " + "; ".join(lines) + "."


@register_tool(
    name="cdp_switch_tab",
    description="Bring a specific tab to the front in Jarvis's dedicated browser by its index (from cdp_list_tabs). This is true per-tab focus.",
    category="web",
)
def cdp_switch_tab(index: int) -> str:
    cdp.ensure()
    t = cdp.activate(int(index))
    if not t:
        return f"There's no tab at index {index}, Sir."
    return f"Switched to tab {index}: {t.get('title') or t.get('url')}, Sir."


@register_tool(
    name="cdp_close_tab",
    description="Close a tab by its index (from cdp_list_tabs) in Jarvis's dedicated browser.",
    category="web",
)
def cdp_close_tab(index: int) -> str:
    cdp.ensure()
    return f"Closed tab {index}, Sir." if cdp.close(int(index)) else f"There's no tab at index {index}, Sir."


@register_tool(
    name="cdp_autofill_login",
    description="Fill the username and password of the login form on the CURRENT page of Jarvis's dedicated browser, using a saved login for the given service. Locates the fields in the page automatically. The password is never shown or spoken.",
    category="security",
)
def cdp_autofill_login(service: str, submit: bool = False) -> str:
    """Find the login fields in the DOM and fill them from the saved credential."""
    cdp.ensure()
    cred = None
    try:
        from jarvis.security.harvester import lookup_browser_login
        cred = lookup_browser_login(service)
    except Exception:
        cred = None
    if not cred:
        try:
            from jarvis.security.vault import vault
            cred = vault.get_credential(service)
        except Exception:
            cred = None
    if not cred or not cred.get("password"):
        return f"I don't have a saved login for '{service}', Sir."

    user = cred.get("username", "") or ""
    pw = cred.get("password", "")
    js = (
        "(function(u,p){"
        "const uf=document.querySelector('input[type=email],input[autocomplete=username],"
        "input[name*=email i],input[name*=user i],input[id*=email i],input[id*=user i],input[type=text]');"
        "const pf=document.querySelector('input[type=password],input[autocomplete=current-password]');"
        "function set(el,v){if(!el)return false;el.focus();el.value=v;"
        "el.dispatchEvent(new Event('input',{bubbles:true}));"
        "el.dispatchEvent(new Event('change',{bubbles:true}));return true;}"
        "const a=set(uf,u),b=set(pf,p);"
        "return JSON.stringify({user:a,pass:b});"
        f"}})({json.dumps(user)},{json.dumps(pw)})"
    )
    try:
        raw = cdp.evaluate(js)
        status = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except Exception as e:
        logger.debug(f"cdp autofill notice: {e}")
        status = {}
    finally:
        pw = ""  # drop plaintext promptly
    if not status.get("pass"):
        return "I couldn't find a password field on this page, Sir."
    if submit:
        cdp.evaluate(
            "(function(){const b=document.querySelector("
            "'button[type=submit],input[type=submit],button[name*=login i],button[id*=login i]');"
            "const pf=document.querySelector('input[type=password]');"
            "if(b){b.click();return 'clicked';} if(pf&&pf.form){pf.form.submit();return 'submitted';} return 'none';})()"
        )
    hint = f" as {user}" if user else ""
    return f"Filled your {service} login{hint}, Sir."
