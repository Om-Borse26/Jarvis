"""
J.A.R.V.I.S. — Credential Harvester
Imports the user's OWN saved logins from local credential stores into the
encrypted vault, so Jarvis can auto-fill / auto-login on command.

Supported sources (what Windows actually lets us read as the logged-in user):
  - Chromium browsers (Brave, Chrome, Edge): `Login Data` SQLite, AES-GCM
    encrypted with a key that is itself DPAPI-protected in `Local State`.
  - Windows Credential Manager: generic credentials stored by desktop apps.

NOT supported (by design of those platforms — they don't store reusable
passwords): Steam, Epic, Battle.net and similar launchers keep OAuth tokens /
session blobs, not passwords. For those, "seamless open" means launching the
app (it stays logged in) or auto-typing a credential you saved yourself.

Security:
  - This reads ONLY the current user's own secrets; it decrypts nothing that
    Windows wouldn't already decrypt for this account.
  - Passwords are re-encrypted at rest in the vault (DPAPI) and are NEVER
    returned to the LLM, spoken, or written to logs. Import tools return counts
    and service/username metadata only.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
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
    if not local_state.exists() or not _HAS_DPAPI:
        return None
    try:
        data = json.loads(local_state.read_text(encoding="utf-8"))
        enc_key_b64 = data["os_crypt"]["encrypted_key"]
        enc_key = base64.b64decode(enc_key_b64)
        # Strip the 5-byte "DPAPI" prefix, then DPAPI-decrypt.
        _desc, key = win32crypt.CryptUnprotectData(enc_key[5:], None, None, None, 0)
        return key
    except Exception as e:
        logger.debug(f"[Harvester] Could not read master key from {user_data_dir}: {e}")
        return None


def _decrypt_chromium_password(blob: bytes, key: bytes | None) -> str | None:
    """Decrypt a single Chromium password blob (AES-GCM v10/v11, or legacy DPAPI)."""
    if not blob:
        return None
    try:
        if blob[:3] in (b"v10", b"v11") and key and _HAS_AESGCM:
            nonce = blob[3:15]
            payload = blob[15:]
            plaintext = AESGCM(key).decrypt(nonce, payload, None)
            return plaintext.decode("utf-8", errors="ignore")
        # Legacy (pre-v80) blobs were DPAPI-encrypted directly.
        if _HAS_DPAPI:
            _desc, data = win32crypt.CryptUnprotectData(blob, None, None, None, 0)
            return data.decode("utf-8", errors="ignore")
    except Exception:
        # v20 "app-bound" entries (newer Chrome) can't be decrypted with the user DPAPI key.
        return None
    return None


def _import_one_chromium(browser: str, user_data_dir: Path) -> tuple[int, int]:
    """Import all profiles of one Chromium browser. Returns (imported, failed)."""
    key = _chromium_master_key(user_data_dir)
    imported = failed = 0

    profiles = [user_data_dir / "Default"]
    profiles += [p for p in user_data_dir.glob("Profile *") if p.is_dir()]

    for profile in profiles:
        login_db = profile / "Login Data"
        if not login_db.exists():
            continue
        # Copy out because the live DB is usually locked by the browser.
        tmp = Path(tempfile.gettempdir()) / f"jarvis_logindata_{browser}_{profile.name}.db"
        try:
            shutil.copy2(login_db, tmp)
            con = sqlite3.connect(tmp)
            rows = con.execute(
                "SELECT origin_url, username_value, password_value FROM logins"
            ).fetchall()
            con.close()
        except Exception as e:
            logger.debug(f"[Harvester] {browser}/{profile.name} read failed: {e}")
            continue
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

        for origin_url, username, pw_blob in rows:
            if not username and not pw_blob:
                continue
            password = _decrypt_chromium_password(pw_blob, key)
            if password is None:
                failed += 1
                continue
            service = urlparse(origin_url).netloc or origin_url or "unknown"
            if vault.set_credential(service, username or "", password, url=origin_url, source=browser):
                imported += 1
            else:
                failed += 1

    return imported, failed


def import_chromium(browser: str | None = None) -> dict:
    """Import saved logins from one or all installed Chromium browsers."""
    if not _LOCALAPPDATA:
        return {"imported": 0, "failed": 0, "sources": []}

    targets = (
        {browser: _CHROMIUM_BROWSERS[browser]}
        if browser and browser in _CHROMIUM_BROWSERS
        else _CHROMIUM_BROWSERS
    )
    total_imported = total_failed = 0
    sources: list[str] = []
    for name, rel in targets.items():
        user_data_dir = Path(_LOCALAPPDATA) / rel
        if not user_data_dir.exists():
            continue
        imp, fail = _import_one_chromium(name, user_data_dir)
        if imp or fail:
            sources.append(f"{name} ({imp})")
        total_imported += imp
        total_failed += fail
    return {"imported": total_imported, "failed": total_failed, "sources": sources}


# ─── Windows Credential Manager ───────────────────────────────────────────────

def import_windows_credentials() -> dict:
    """Import generic credentials stored in Windows Credential Manager."""
    if not _HAS_WINCRED:
        return {"imported": 0, "failed": 0}
    imported = failed = 0
    try:
        creds = win32cred.CredEnumerate(None, 0)
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
    description="Import the user's OWN saved logins from local stores (browsers, Windows Credential Manager) into the encrypted vault so Jarvis can auto-fill them later. Use when the user asks Jarvis to learn or import their saved passwords. Returns only counts — never the actual passwords.",
    category="security",
)
def import_credentials(source: str = "all") -> str:
    """Harvest saved logins into the vault. `source`: all | browsers | brave | chrome | edge | windows."""
    src = (source or "all").strip().lower()
    parts: list[str] = []
    total = 0

    if src in ("all", "browsers", "brave", "chrome", "edge"):
        browser = {"brave": "Brave", "chrome": "Chrome", "edge": "Edge"}.get(src)
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
        return "I didn't find any readable saved logins to import."
    detail = "; ".join(parts) if parts else ""
    return f"Imported {total} logins into the encrypted vault ({detail}). Passwords stay encrypted and are never shown."


@register_tool(
    name="find_login",
    description="Find whether a saved login exists for a service or website and report its username. Never reveals the password.",
    category="security",
)
def find_login(service: str) -> str:
    """Look up a saved login by service/website name (metadata only)."""
    matches = vault.find_credentials(service)
    if not matches:
        return f"I don't have a saved login for '{service}'."
    top = matches[:5]
    listed = "; ".join(f"{m['service']} (user: {m['username'] or 'n/a'})" for m in top)
    more = "" if len(matches) <= 5 else f" and {len(matches) - 5} more"
    return f"I have saved logins for: {listed}{more}."


@register_tool(
    name="list_logins",
    description="List how many logins are stored and the services/usernames (never passwords).",
    category="security",
)
def list_logins() -> str:
    """Summarize stored logins without revealing any passwords."""
    n = vault.count_credentials()
    if n == 0:
        return "No logins are stored in the vault yet."
    sample = vault.find_credentials("")[:10]
    names = ", ".join(sorted({m["service"] for m in sample}))
    return f"I have {n} logins stored. Examples: {names}."


@register_tool(
    name="autofill_login",
    description="Type a stored login into the CURRENTLY FOCUSED login form (username, Tab, password, Enter). Use after opening an app or website and clicking the username field. The password is typed directly and is never shown or spoken.",
    category="security",
)
def autofill_login(service: str, mode: str = "user_pass") -> str:
    """Type a vaulted credential into the focused field. mode: user_pass | password_only."""
    cred = vault.get_credential(service)
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
