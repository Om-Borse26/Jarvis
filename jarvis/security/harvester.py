"""
J.A.R.V.I.S. — Credential Access (Hybrid)
Gives Jarvis access to the user's OWN saved logins so it can auto-fill / log in.

Hybrid model (smallest stored footprint):
  - Browser logins (Brave/Chrome/Edge) are read DECRYPT-ON-DEMAND: the matching
    password is decrypted straight from the browser store at the moment it's
    needed and wiped right after. Jarvis keeps NO second copy of them.
  - The vault is used only for credentials that have no other home: tokens/keys
    the user gives directly, and Windows Credential Manager entries (optional
    import).

Browser decryption: `Login Data` SQLite with AES-GCM values whose key lives,
DPAPI-protected, in `Local State` — readable only by the current Windows user.

NOT supported (those platforms don't store reusable passwords — they keep OAuth
tokens/session blobs): Steam, Epic, Battle.net and similar launchers. For those,
"seamless open" means launching the app (it stays logged in).

Security: passwords are never returned to the LLM, spoken, or written to logs.
Lookups return counts and service/username metadata only.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from loguru import logger

from jarvis.security.vault import vault
from jarvis.tools.registry import register_tool

try:
    import win32crypt  # pywin32
    _HAS_DPAPI = True
except Exception:
    win32crypt = None
    _HAS_DPAPI = False

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    _HAS_AESGCM = True
except Exception:
    AESGCM = None
    _HAS_AESGCM = False

try:
    import win32cred  # pywin32
    _HAS_WINCRED = True
except Exception:
    win32cred = None
    _HAS_WINCRED = False


_LOCALAPPDATA = os.environ.get("LOCALAPPDATA", "")

# Browser name → path to its "User Data" root under %LOCALAPPDATA%.
_CHROMIUM_BROWSERS = {
    "Brave": r"BraveSoftware\Brave-Browser\User Data",
    "Chrome": r"Google\Chrome\User Data",
    "Edge": r"Microsoft\Edge\User Data",
}


# ─── Chromium ─────────────────────────────────────────────────────────────────

def _chromium_master_key(user_data_dir: Path) -> bytes | None:
    """Read and DPAPI-decrypt the AES master key from a browser's Local State."""
    local_state = user_data_dir / "Local State"
    if not local_state.exists() or not _HAS_DPAPI or win32crypt is None:
        return None
    try:
        data = json.loads(local_state.read_text(encoding="utf-8"))
        enc_key_b64 = data["os_crypt"]["encrypted_key"]
        enc_key = base64.b64decode(enc_key_b64)
        # Strip the 5-byte "DPAPI" prefix, then DPAPI-decrypt.
        _wc: Any = win32crypt
        _desc, key = _wc.CryptUnprotectData(enc_key[5:], None, None, None, 0)
        return key
    except Exception as e:
        logger.debug(f"[Harvester] Could not read master key from {user_data_dir}: {e}")
        return None


def _decrypt_chromium_password(blob: bytes, key: bytes | None) -> str | None:
    """Decrypt a single Chromium password blob (AES-GCM v10/v11, or legacy DPAPI)."""
    if not blob:
        return None
    try:
        if blob[:3] in (b"v10", b"v11") and key and _HAS_AESGCM and AESGCM is not None:
            nonce = blob[3:15]
            payload = blob[15:]
            _aesgcm_cls: Any = AESGCM
            plaintext = _aesgcm_cls(key).decrypt(nonce, payload, None)
            return plaintext.decode("utf-8", errors="ignore")
        # Legacy (pre-v80) blobs were DPAPI-encrypted directly.
        if _HAS_DPAPI and win32crypt is not None:
            _wc: Any = win32crypt
            _desc, data = _wc.CryptUnprotectData(blob, None, None, None, 0)
            return data.decode("utf-8", errors="ignore")
    except Exception:
        # v20 "app-bound" entries (newer Chrome) can't be decrypted with the user DPAPI key.
        return None
    return None


def _iter_login_rows():
    """Yield (browser, master_key, origin_url, username, password_blob) for every Chromium login."""
    if not _LOCALAPPDATA:
        return
    for name, rel in _CHROMIUM_BROWSERS.items():
        user_data_dir = Path(_LOCALAPPDATA) / rel
        if not user_data_dir.exists():
            continue
        key = _chromium_master_key(user_data_dir)
        profiles = [user_data_dir / "Default"]
        profiles += [p for p in user_data_dir.glob("Profile *") if p.is_dir()]
        for profile in profiles:
            login_db = profile / "Login Data"
            if not login_db.exists():
                continue
            # Copy out because the live DB is usually locked by the browser.
            tmp = Path(tempfile.gettempdir()) / f"jarvis_logindata_{name}_{profile.name}.db"
            try:
                shutil.copy2(login_db, tmp)
                con = sqlite3.connect(tmp)
                rows = con.execute(
                    "SELECT origin_url, username_value, password_value FROM logins"
                ).fetchall()
                con.close()
            except Exception as e:
                logger.debug(f"[Harvester] {name}/{profile.name} read failed: {e}")
                continue
            finally:
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass
            for origin_url, username, pw_blob in rows:
                yield name, key, origin_url, username, pw_blob


def lookup_browser_login(query: str) -> dict | None:
    """Decrypt ONE matching browser login on demand (no stored copy). In-process ONLY."""
    q = (query or "").strip().lower()
    if not q:
        return None
    for browser, key, origin_url, username, pw_blob in _iter_login_rows():
        host = urlparse(origin_url).netloc.lower()
        if q in host or q in (origin_url or "").lower():
            password = _decrypt_chromium_password(pw_blob, key)
            if password:
                return {
                    "service": host or origin_url,
                    "username": username or "",
                    "password": password,
                    "url": origin_url,
                    "source": browser,
                }
    return None


def list_browser_logins(query: str = "") -> list[dict]:
    """List browser-login metadata on demand — NEVER decrypts or returns passwords."""
    q = (query or "").strip().lower()
    out: list[dict] = []
    seen: set = set()
    for browser, _key, origin_url, username, _pw_blob in _iter_login_rows():
        host = urlparse(origin_url).netloc
        if q and q not in host.lower() and q not in (origin_url or "").lower():
            continue
        dedup = (host, username)
        if dedup in seen:
            continue
        seen.add(dedup)
        out.append({"service": host or origin_url, "username": username or "", "url": origin_url, "source": browser})
    return out


def import_chromium(browser: str | None = None) -> dict:
    """Bulk-copy saved logins from Chromium browsers into the vault (optional opt-in)."""
    imported = failed = 0
    sources: dict[str, int] = {}
    want = {"brave": "Brave", "chrome": "Chrome", "edge": "Edge"}.get((browser or "").lower())
    for name, key, origin_url, username, pw_blob in _iter_login_rows():
        if want and name != want:
            continue
        if not username and not pw_blob:
            continue
        password = _decrypt_chromium_password(pw_blob, key)
        if password is None:
            failed += 1
            continue
        service = urlparse(origin_url).netloc or origin_url or "unknown"
        if vault.set_credential(service, username or "", password, url=origin_url, source=name):
            imported += 1
            sources[name] = sources.get(name, 0) + 1
        else:
            failed += 1
    return {
        "imported": imported,
        "failed": failed,
        "sources": [f"{k} ({v})" for k, v in sources.items()],
    }


# ─── Windows Credential Manager ───────────────────────────────────────────────

def import_windows_credentials() -> dict:
    """Import generic credentials stored in Windows Credential Manager."""
    if not _HAS_WINCRED or win32cred is None:
        return {"imported": 0, "failed": 0}
    imported = failed = 0
    try:
        _wc: Any = win32cred
        creds = _wc.CredEnumerate(None, 0)
    except Exception as e:
        logger.debug(f"[Harvester] Credential Manager enumerate failed: {e}")
        return {"imported": 0, "failed": 0}

    for c in creds or []:
        try:
            blob = c.get("CredentialBlob")
            if not blob:
                continue
            # Blobs are commonly UTF-16-LE; fall back to UTF-8.
            try:
                password = bytes(blob).decode("utf-16-le", errors="ignore").rstrip("\x00")
            except Exception:
                password = bytes(blob).decode("utf-8", errors="ignore")
            if not password:
                continue
            service = c.get("TargetName", "") or "unknown"
            username = c.get("UserName", "") or ""
            if vault.set_credential(service, username, password, source="WindowsCredentialManager"):
                imported += 1
        except Exception:
            failed += 1
    return {"imported": imported, "failed": failed}


# ─── Agent-exposed tools (counts & metadata only — never passwords) ───────────

@register_tool(
    name="import_credentials",
    description="Import credentials into the encrypted vault. Browser logins (Brave/Chrome/Edge) are read on demand and normally do NOT need importing; use this mainly to pull Windows Credential Manager entries, or pass source='browsers' to also keep an offline copy of browser logins. Returns only counts — never passwords.",
    category="security",
)
def import_credentials(source: str = "windows") -> str:
    """Import logins into the vault. source: windows | browsers | brave | chrome | edge | all."""
    src = (source or "windows").strip().lower()
    parts: list[str] = []
    total = 0

    if src in ("all", "browsers", "brave", "chrome", "edge"):
        browser = {"brave": "brave", "chrome": "chrome", "edge": "edge"}.get(src)
        res = import_chromium(browser)
        total += res["imported"]
        if res["sources"]:
            parts.append("browsers: " + ", ".join(res["sources"]))
    if src in ("all", "windows"):
        res = import_windows_credentials()
        total += res["imported"]
        if res["imported"]:
            parts.append(f"Windows Credential Manager: {res['imported']}")

    if total == 0:
        return "I didn't find any readable credentials to import."
    detail = "; ".join(parts) if parts else ""
    return f"Imported {total} credentials into the encrypted vault ({detail}). Passwords stay encrypted and are never shown."


@register_tool(
    name="find_login",
    description="Find whether a login exists for a service or website and report its username. Checks both the browser stores (on demand) and the vault. Never reveals the password.",
    category="security",
)
def find_login(service: str) -> str:
    """Look up a saved login by service/website name (metadata only)."""
    matches = list_browser_logins(service) + vault.find_credentials(service)
    # De-duplicate by (service, username).
    seen, unique = set(), []
    for m in matches:
        key = (m["service"], m.get("username", ""))
        if key in seen:
            continue
        seen.add(key)
        unique.append(m)
    if not unique:
        return f"I don't have a saved login for '{service}'."
    top = unique[:5]
    listed = "; ".join(f"{m['service']} (user: {m['username'] or 'n/a'})" for m in top)
    more = "" if len(unique) <= 5 else f" and {len(unique) - 5} more"
    return f"I have saved logins for: {listed}{more}."


@register_tool(
    name="list_logins",
    description="List how many logins are available (browser stores + vault) and some example services. Never reveals passwords.",
    category="security",
)
def list_logins() -> str:
    """Summarize available logins without revealing any passwords."""
    browser = list_browser_logins("")
    vault_n = vault.count_credentials()
    total = len(browser) + vault_n
    if total == 0:
        return "No logins are available yet."
    services = sorted({m["service"] for m in browser[:20]} | {m["service"] for m in vault.find_credentials("")[:20]})
    names = ", ".join(services[:10])
    return f"I have about {total} logins available. Examples: {names}."


@register_tool(
    name="autofill_login",
    description="Type a saved login into the CURRENTLY FOCUSED login form (username, Tab, password, Enter). Prefers the live browser store, falls back to the vault. Use after opening an app/site and clicking the username field. The password is typed directly and is never shown or spoken.",
    category="security",
)
def autofill_login(service: str, mode: str = "user_pass") -> str:
    """Type a credential into the focused field. mode: user_pass | password_only."""
    # Hybrid: decrypt on demand from the browser first; fall back to the vault.
    cred = lookup_browser_login(service) or vault.get_credential(service)
    if not cred:
        return f"I don't have a saved login for '{service}'."
    try:
        import pyautogui
    except Exception:
        return "Keyboard automation isn't available, so I can't auto-fill the login."

    try:
        if mode == "password_only":
            pyautogui.typewrite(cred["password"], interval=0.02)
            pyautogui.press("enter")
        else:
            pyautogui.typewrite(cred["username"], interval=0.02)
            pyautogui.press("tab")
            pyautogui.typewrite(cred["password"], interval=0.02)
            pyautogui.press("enter")
    except Exception as e:
        logger.error(f"[Harvester] autofill failed: {e}")
        return "I couldn't type the login into the form."
    finally:
        cred["password"] = ""  # drop the plaintext from memory promptly

    user_hint = f" as {cred['username']}" if mode != "password_only" and cred["username"] else ""
    return f"Signed you in to {cred['service']}{user_hint}."
