"""
J.A.R.V.I.S. — Encrypted Secrets Vault
Stores credentials (API keys, tokens, passwords) encrypted at rest.

Security model:
  - Primary backend: Windows DPAPI (`win32crypt`). Ciphertext is bound to the
    current Windows user account — it cannot be decrypted by another user or on
    another machine, and there is no master password to manage or leak.
  - Fallback backend: Fernet (AES-128-CBC + HMAC) from the `cryptography`
    package, with the key held in the OS keyring (never on disk in plaintext).
  - Secret VALUES are NEVER returned to the LLM, spoken aloud, or written to the
    audit log. The tools exposed to the agent only store, list, check, or delete.
    Code that must actually USE a secret calls `vault.get_secret()` in-process.
"""
from __future__ import annotations

import base64
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from jarvis.core.config import load_config
from jarvis.tools.registry import register_tool

# ── Optional backends (import-guarded so the module never hard-fails) ─────────
try:
    import win32crypt  # from pywin32
    _HAS_DPAPI = True
except Exception:  # pragma: no cover - non-Windows / missing pywin32
    win32crypt = None
    _HAS_DPAPI = False

try:
    from cryptography.fernet import Fernet
    _HAS_FERNET = True
except Exception:  # pragma: no cover
    Fernet = None
    _HAS_FERNET = False

try:
    import keyring
    _HAS_KEYRING = True
except Exception:  # pragma: no cover
    keyring = None
    _HAS_KEYRING = False


_KEYRING_SERVICE = "jarvis-vault"
_KEYRING_USER = "fernet-key"


def _resolve_vault_path() -> Path:
    try:
        cfg = load_config()
        path = cfg.get("vault", {}).get("vault_path", "data/vault.db")
    except Exception:
        path = "data/vault.db"
    return Path(path)


class SecretsVault:
    """Encrypted key/value store for credentials. Singleton-style module instance."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path) if db_path else _resolve_vault_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._backend = "dpapi" if _HAS_DPAPI else ("fernet" if _HAS_FERNET else "none")
        self._fernet: Any = self._init_fernet() if self._backend == "fernet" else None
        self._init_db()
        logger.info(f"[Vault] Ready (backend={self._backend}, store={self.db_path}).")

    # ── Backend setup ─────────────────────────────────────────────────────────
    def _init_db(self) -> None:
        con = sqlite3.connect(self.db_path)
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS secrets (
                name    TEXT PRIMARY KEY,
                blob    TEXT NOT NULL,
                backend TEXT NOT NULL,
                created REAL NOT NULL,
                updated REAL NOT NULL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS credentials (
                service  TEXT NOT NULL,
                username TEXT NOT NULL,
                blob     TEXT NOT NULL,
                url      TEXT DEFAULT '',
                source   TEXT DEFAULT '',
                backend  TEXT NOT NULL,
                created  REAL NOT NULL,
                updated  REAL NOT NULL,
                PRIMARY KEY (service, username)
            )
            """
        )
        con.commit()
        con.close()

    def _init_fernet(self) -> Any:
        if not _HAS_FERNET or Fernet is None:
            return None
        _fernet_cls: Any = Fernet
        key = None
        if _HAS_KEYRING and keyring is not None:
            _kr: Any = keyring
            try:
                key = _kr.get_password(_KEYRING_SERVICE, _KEYRING_USER)
            except Exception as e:
                logger.warning(f"[Vault] Keyring read notice: {e}")
        if not key:
            key = _fernet_cls.generate_key().decode()
            if _HAS_KEYRING and keyring is not None:
                _kr = keyring
                try:
                    _kr.set_password(_KEYRING_SERVICE, _KEYRING_USER, key)
                except Exception as e:
                    logger.warning(f"[Vault] Keyring write notice: {e}")
        return _fernet_cls(key.encode() if isinstance(key, str) else key)

    # ── Encryption primitives ────────────────────────────────────────────────
    def _encrypt(self, plaintext: str) -> str:
        data = plaintext.encode("utf-8")
        if self._backend == "dpapi" and _HAS_DPAPI and win32crypt is not None:
            _wc: Any = win32crypt
            blob = _wc.CryptProtectData(data, "jarvis-secret", None, None, None, 0)
            return base64.b64encode(blob).decode("ascii")
        if self._backend == "fernet" and self._fernet is not None:
            return base64.b64encode(self._fernet.encrypt(data)).decode("ascii")
        raise RuntimeError("No encryption backend available to store secrets safely.")

    def _decrypt(self, blob_b64: str, backend: str) -> str:
        raw = base64.b64decode(blob_b64.encode("ascii"))
        if backend == "dpapi":
            if not _HAS_DPAPI or win32crypt is None:
                raise RuntimeError("Secret was stored with DPAPI but DPAPI is unavailable.")
            _wc: Any = win32crypt
            _desc, data = _wc.CryptUnprotectData(raw, None, None, None, 0)
            return data.decode("utf-8")
        if backend == "fernet":
            if not self._fernet:
                raise RuntimeError("Secret was stored with Fernet but no key is available.")
            return self._fernet.decrypt(raw).decode("utf-8")
        raise RuntimeError(f"Unknown vault backend '{backend}'.")

    # ── Public API (in-process; values stay in memory only) ───────────────────
    def set_secret(self, name: str, value: str) -> bool:
        name = (name or "").strip()
        if not name or value is None:
            return False
        try:
            blob = self._encrypt(value)
            now = time.time()
            con = sqlite3.connect(self.db_path)
            con.execute(
                """
                INSERT INTO secrets (name, blob, backend, created, updated)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    blob=excluded.blob, backend=excluded.backend, updated=excluded.updated
                """,
                (name, blob, self._backend, now, now),
            )
            con.commit()
            con.close()
            return True
        except Exception as e:
            logger.error(f"[Vault] Failed to store '{name}': {e}")
            return False

    def get_secret(self, name: str) -> Optional[str]:
        """Return the decrypted secret value. In-process use ONLY — never speak/log this."""
        name = (name or "").strip()
        if not name:
            return None
        try:
            con = sqlite3.connect(self.db_path)
            row = con.execute(
                "SELECT blob, backend FROM secrets WHERE name = ?", (name,)
            ).fetchone()
            con.close()
            if not row:
                return None
            return self._decrypt(row[0], row[1])
        except Exception as e:
            logger.error(f"[Vault] Failed to retrieve '{name}': {e}")
            return None

    def has_secret(self, name: str) -> bool:
        name = (name or "").strip()
        if not name:
            return False
        con = sqlite3.connect(self.db_path)
        row = con.execute("SELECT 1 FROM secrets WHERE name = ?", (name,)).fetchone()
        con.close()
        return row is not None

    def list_names(self) -> list[str]:
        con = sqlite3.connect(self.db_path)
        rows = con.execute("SELECT name FROM secrets ORDER BY name").fetchall()
        con.close()
        return [r[0] for r in rows]

    def delete_secret(self, name: str) -> bool:
        name = (name or "").strip()
        if not name:
            return False
        con = sqlite3.connect(self.db_path)
        cur = con.execute("DELETE FROM secrets WHERE name = ?", (name,))
        con.commit()
        deleted = cur.rowcount > 0
        con.close()
        return deleted

    # ── Structured logins (service / username / password) ─────────────────────
    def set_credential(
        self, service: str, username: str, password: str,
        url: str = "", source: str = "",
    ) -> bool:
        """Store or update one login. Password is encrypted at rest."""
        service = (service or "").strip()
        username = (username or "").strip()
        if not service or password is None:
            return False
        try:
            blob = self._encrypt(password)
            now = time.time()
            con = sqlite3.connect(self.db_path)
            con.execute(
                """
                INSERT INTO credentials (service, username, blob, url, source, backend, created, updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(service, username) DO UPDATE SET
                    blob=excluded.blob, url=excluded.url, source=excluded.source,
                    backend=excluded.backend, updated=excluded.updated
                """,
                (service, username, blob, url, source, self._backend, now, now),
            )
            con.commit()
            con.close()
            return True
        except Exception as e:
            logger.error(f"[Vault] Failed to store credential for '{service}': {e}")
            return False

    def get_credential(self, service: str, username: Optional[str] = None) -> Optional[dict]:
        """Return {service, username, password, url} for a login. In-process ONLY."""
        service = (service or "").strip()
        if not service:
            return None
        try:
            con = sqlite3.connect(self.db_path)
            if username:
                row = con.execute(
                    "SELECT service, username, blob, backend, url FROM credentials "
                    "WHERE service = ? AND username = ?",
                    (service, username.strip()),
                ).fetchone()
            else:
                row = con.execute(
                    "SELECT service, username, blob, backend, url FROM credentials "
                    "WHERE service = ? OR service LIKE ? ORDER BY updated DESC LIMIT 1",
                    (service, f"%{service}%"),
                ).fetchone()
            con.close()
            if not row:
                return None
            return {
                "service": row[0],
                "username": row[1],
                "password": self._decrypt(row[2], row[3]),
                "url": row[4],
            }
        except Exception as e:
            logger.error(f"[Vault] Failed to retrieve credential for '{service}': {e}")
            return None

    def find_credentials(self, query: str = "") -> list[dict]:
        """Search logins by service/username. Returns metadata only — NEVER passwords."""
        con = sqlite3.connect(self.db_path)
        if query:
            q = f"%{query.strip()}%"
            rows = con.execute(
                "SELECT service, username, url, source FROM credentials "
                "WHERE service LIKE ? OR username LIKE ? OR url LIKE ? ORDER BY service",
                (q, q, q),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT service, username, url, source FROM credentials ORDER BY service"
            ).fetchall()
        con.close()
        return [{"service": r[0], "username": r[1], "url": r[2], "source": r[3]} for r in rows]

    def count_credentials(self) -> int:
        con = sqlite3.connect(self.db_path)
        n = con.execute("SELECT COUNT(*) FROM credentials").fetchone()[0]
        con.close()
        return int(n)

    def delete_credential(self, service: str, username: Optional[str] = None) -> int:
        service = (service or "").strip()
        if not service:
            return 0
        con = sqlite3.connect(self.db_path)
        if username:
            cur = con.execute(
                "DELETE FROM credentials WHERE service = ? AND username = ?",
                (service, username.strip()),
            )
        else:
            cur = con.execute("DELETE FROM credentials WHERE service = ?", (service,))
        con.commit()
        n = cur.rowcount
        con.close()
        return n


# Global singleton vault instance
vault = SecretsVault()


# ─── Agent-exposed tools (never return raw secret values) ─────────────────────

@register_tool(
    name="save_secret",
    description="Securely store a credential (API key, token, or password) in the encrypted vault. The value is encrypted at rest and is never spoken or shown. Use when the user says to remember a password, key, or token.",
    category="security",
)
def save_secret(name: str, value: str = "", secret: str = "", *args, **kwargs) -> str:
    """Encrypt and store a named secret. Returns a masked confirmation only."""
    val = value or secret
    ok = vault.set_secret(name, val)
    if ok:
        return f"Stored the credential '{name}' securely in the encrypted vault."
    return f"I was unable to store the credential '{name}'."


@register_tool(
    name="list_secrets",
    description="List the NAMES of credentials stored in the vault. Values are never revealed.",
    category="security",
)
def list_secrets() -> str:
    """Return the names of stored secrets (never the values)."""
    names = vault.list_names()
    if not names:
        return "The vault is empty — no credentials are stored yet."
    return "Stored credentials: " + ", ".join(names) + "."


@register_tool(
    name="check_secret",
    description="Check whether a named credential exists in the vault. Does not reveal the value.",
    category="security",
)
def check_secret(name: str) -> str:
    """Report whether a secret exists, without revealing it."""
    return (
        f"Yes, a credential named '{name}' is stored in the vault."
        if vault.has_secret(name)
        else f"No credential named '{name}' is stored in the vault."
    )


@register_tool(
    name="delete_secret",
    description="Permanently delete a stored credential from the vault by name.",
    category="security",
)
def delete_secret(name: str) -> str:
    """Delete a secret from the vault."""
    return (
        f"Deleted the credential '{name}' from the vault."
        if vault.delete_secret(name)
        else f"There was no credential named '{name}' to delete."
    )
