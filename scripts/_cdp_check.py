"""Live CDP browser probe: open, tabs, per-tab switch, and DOM autofill."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from loguru import logger
logger.remove(); logger.add(sys.stderr, level="WARNING")

import jarvis.tools  # noqa
from jarvis.tools.cdp_browser import (
    cdp, cdp_open_browser, cdp_list_tabs, cdp_switch_tab, cdp_close_tab, cdp_autofill_login,
)
from jarvis.security.vault import vault

LOGIN_FORM = ("data:text/html,<html><body><h1>Login</h1><form>"
              "<input id=u type=text><input id=p type=password>"
              "<button type=submit>Sign in</button></form></body></html>")

print("1) open dedicated browser ->", cdp_open_browser("https://example.com"))
time.sleep(1)

# Open a login page; new_tab makes it the current tab (real flow: 'sign me in').
cdp.new_tab(LOGIN_FORM)
time.sleep(1.2)
vault.set_credential("testsite", "tomsmith", "SuperSecretPassword!", url="data:login")
print("2) autofill current login tab ->", cdp_autofill_login("testsite"))
time.sleep(0.3)
filled = cdp.evaluate("document.querySelector('input[type=text]').value+'|'"
                      "+document.querySelector('input[type=password]').value")
print("   filled values ->", filled)
print("   AUTOFILL PASS:", filled == "tomsmith|SuperSecretPassword!")

tabs = cdp_list_tabs()
print("3) list tabs ->", len(tabs), "tabs")
print("4) switch to tab 0 ->", cdp_switch_tab(0))
last = len(cdp.list_tabs()) - 1
print(f"5) switch to last tab {last} ->", cdp_switch_tab(last))
print("6) close last tab ->", cdp_close_tab(last))

try:
    vault.delete_secret("cred:testsite")
except Exception:
    pass
