"""
J.A.R.V.I.S. — Local Control Server
Serves the orb overlay and the dashboard, and exposes a small REST API the
dashboard uses to read stats and (only from here) change what Jarvis may access.

Stdlib-only HTTP server on localhost, run in a daemon thread. Endpoints:
  GET  /                     → dashboard
  GET  /orb                  → orb overlay
  GET  /api/state            → current state (idle/listening/thinking/speaking)
  GET  /api/permissions      → user permission policy
  POST /api/permissions      → {category, enabled}  (THE control surface)
  GET  /api/reminders        → active reminders/meetings
  POST /api/reminders/cancel → {id}
  GET  /api/history          → recent interactions
  GET  /api/audit            → recent audited actions
  GET  /api/startup          → {enabled}
  POST /api/startup          → {enabled}
  POST /api/stop             → shut Jarvis down
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from loguru import logger

from jarvis.tools.registry import register_tool

_WEB_DIR = Path(__file__).parent / "web"
_CTYPES = {".html": "text/html", ".css": "text/css", ".js": "application/javascript",
           ".png": "image/png", ".svg": "image/svg+xml"}


def _read_audit_tail(limit: int = 50) -> list[dict]:
    path = Path("data/logs/audit.jsonl")
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
        out = []
        for ln in reversed(lines):
            try:
                out.append(json.loads(ln))
            except Exception:
                continue
        return out
    except Exception:
        return []


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence default request logging
        return

    # ── helpers ───────────────────────────────────────────────────────────────
    def _json(self, obj: Any, code: int = 200) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, name: str) -> None:
        path = _WEB_DIR / name
        if not path.exists():
            self.send_error(404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", _CTYPES.get(path.suffix, "text/plain"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    # ── routes ────────────────────────────────────────────────────────────────
    def do_GET(self):
        r = self.path.split("?")[0]
        if r in ("/", "/dashboard"):
            return self._file("dashboard.html")
        if r == "/orb":
            return self._file("orb.html")
        if r.startswith("/static/"):
            return self._file(r[len("/static/"):])
        if r == "/api/state":
            from jarvis.ui.state import state_bridge
            return self._json(state_bridge.snapshot())
        if r == "/api/permissions":
            from jarvis.core.permissions import permission_policy, KNOWN_CATEGORIES
            return self._json({"categories": KNOWN_CATEGORIES, "policy": permission_policy.as_dict()})
        if r == "/api/reminders":
            from jarvis.core.scheduler import scheduler
            return self._json({"reminders": scheduler.list_jobs()})
        if r == "/api/history":
            from jarvis.memory.episodic import episodic_memory
            return self._json({"history": episodic_memory.recent(15)})
        if r == "/api/audit":
            return self._json({"audit": _read_audit_tail(50)})
        if r == "/api/startup":
            from jarvis.core.lifecycle import is_startup_enabled
            return self._json({"enabled": is_startup_enabled()})
        return self.send_error(404)

    def do_POST(self):
        r = self.path.split("?")[0]
        body = self._body()
        if r == "/api/permissions":
            from jarvis.core.permissions import permission_policy
            cat = body.get("category", "")
            enabled = bool(body.get("enabled", True))
            if cat:
                permission_policy.set(cat, enabled)
            return self._json({"ok": True, "policy": permission_policy.as_dict()})
        if r == "/api/reminders/cancel":
            from jarvis.core.scheduler import scheduler
            return self._json({"ok": scheduler.cancel(int(body.get("id", -1)))})
        if r == "/api/startup":
            from jarvis.core.lifecycle import enable_startup, disable_startup
            ok = enable_startup() if body.get("enabled") else disable_startup()
            return self._json({"ok": ok})
        if r == "/api/stop":
            from jarvis.core.lifecycle import request_shutdown
            request_shutdown()
            return self._json({"ok": True})
        return self.send_error(404)


class ControlServer:
    """Runs the local HTTP control server in a daemon thread."""

    def __init__(self, port: int = 8787) -> None:
        self.port = port
        self._httpd = None

    def start(self) -> bool:
        try:
            self._httpd = ThreadingHTTPServer(("127.0.0.1", self.port), _Handler)
        except Exception as e:
            logger.warning(f"[UI] Control server could not bind port {self.port}: {e}")
            return False
        threading.Thread(target=self._httpd.serve_forever, name="jarvis-ui-server", daemon=True).start()
        logger.success(f"[UI] Control server on http://127.0.0.1:{self.port}")
        return True

    def stop(self) -> None:
        if self._httpd:
            try:
                self._httpd.shutdown()
            except Exception:
                pass


@register_tool(
    name="open_dashboard",
    description="Open the Jarvis dashboard (stats, reminders, access controls) in the browser.",
    category="system",
)
def open_dashboard() -> str:
    """Open the local dashboard in the default browser."""
    try:
        import webbrowser
        from jarvis.core.config import load_config
        port = int(load_config().get("ui", {}).get("http_port", 8787))
        webbrowser.open(f"http://127.0.0.1:{port}/")
        return "Opening your dashboard."
    except Exception as e:
        return f"I couldn't open the dashboard: {e}"
