"""
J.A.R.V.I.S. — Eve Sync Server
Exposes Eve to your phone over the local network. Your phone's browser opens the
Eve PWA; all API calls are authenticated with a pairing token.

Endpoints (all under /eve):
  GET  /eve                → the Eve PWA (phone chat UI)
  POST /eve/chat           → {text} → Eve's reply (token required)
  GET  /eve/pending        → tasks Jarvis queued for you (token required)
  POST /eve/ack            → {id} acknowledge an item
  POST /eve/note           → {text} leave a note for Jarvis
  GET  /eve/ping           → connectivity check

Security: binds to the LAN, requires the pairing token (X-Eve-Token header or
?token=) on every data call. The token is generated once and stored locally.
"""
from __future__ import annotations

import json
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs

from loguru import logger

_WEB_DIR = Path(__file__).parent / "web"
_TOKEN_FILE = Path("data/eve_token.txt")


def _load_or_create_token() -> str:
    try:
        if _TOKEN_FILE.exists():
            tok = _TOKEN_FILE.read_text(encoding="utf-8").strip()
            if tok:
                return tok
        tok = secrets.token_urlsafe(18)
        _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        _TOKEN_FILE.write_text(tok, encoding="utf-8")
        return tok
    except Exception:
        return secrets.token_urlsafe(18)


def _lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


TOKEN = _load_or_create_token()


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self) -> bool:
        tok = self.headers.get("X-Eve-Token", "")
        if not tok:
            tok = parse_qs(urlparse(self.path).query).get("token", [""])[0]
        return secrets.compare_digest(tok, TOKEN)

    def _body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    def do_GET(self):
        r = urlparse(self.path).path
        if r in ("/eve", "/eve/"):
            path = _WEB_DIR / "eve.html"
            if not path.exists():
                return self.send_error(404)
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if r == "/eve/ping":
            return self._json({"ok": True})
        if r == "/eve/pending":
            if not self._authed():
                return self._json({"error": "unauthorized"}, 401)
            from jarvis.eve.companion import eve
            return self._json({"pending": eve.pending_from_jarvis()})
        return self.send_error(404)

    def do_POST(self):
        r = urlparse(self.path).path
        if not self._authed():
            return self._json({"error": "unauthorized"}, 401)
        body = self._body()
        from jarvis.eve.companion import eve
        if r == "/eve/chat":
            return self._json({"reply": eve.process(body.get("text", ""))})
        if r == "/eve/ack":
            eve.ack(int(body.get("id", -1)))
            return self._json({"ok": True})
        if r == "/eve/note":
            eve.note_for_jarvis(body.get("text", ""))
            return self._json({"ok": True})
        return self.send_error(404)


class EveSyncServer:
    """Runs the Eve LAN sync server in a daemon thread."""

    def __init__(self, port: int = 8765, bind: str = "0.0.0.0") -> None:
        self.port = port
        self.bind = bind
        self._httpd = None

    def start(self) -> bool:
        try:
            self._httpd = ThreadingHTTPServer((self.bind, self.port), _Handler)
        except Exception as e:
            logger.warning(f"[Eve] sync server could not bind {self.bind}:{self.port}: {e}")
            return False
        threading.Thread(target=self._httpd.serve_forever, name="eve-sync", daemon=True).start()
        url = f"http://{_lan_ip()}:{self.port}/eve"
        logger.success(f"[Eve] Companion reachable at {url}  (pairing token: {TOKEN})")
        return True

    def stop(self) -> None:
        if self._httpd:
            try:
                self._httpd.shutdown()
            except Exception:
                pass
