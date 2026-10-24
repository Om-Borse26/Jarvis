"""
J.A.R.V.I.S. — Real MCP Runtime (stdio JSON-RPC client)
Spawns configured MCP servers as child processes, performs the MCP handshake,
discovers their tools at runtime, and registers each one into Jarvis's central
registry so the agent loop can call them natively.

Transport: newline-delimited JSON-RPC 2.0 over the server's stdin/stdout
(the MCP stdio transport). No third-party MCP SDK required.

Lifecycle:
  manager.start_all()  → launch every enabled server, handshake, discover tools
  <agent calls "<server>_<tool>" like any other tool>
  manager.stop_all()   → terminate all server processes
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from jarvis.tools.registry import registry, ToolParameter, register_tool

CONFIG_PATH = Path("config/mcp_servers.json")
_PROTOCOL_VERSION = "2024-11-05"


class MCPError(Exception):
    """A JSON-RPC error returned by an MCP server."""


class MCPClient:
    """Manages one MCP server subprocess and its JSON-RPC conversation."""

    def __init__(self, name: str, command: str, args: Optional[list] = None, env: Optional[dict] = None):
        self.name = name
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.tools: List[dict] = []
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._pending: Dict[int, asyncio.Future] = {}
        self._next_id = 0

    # ── Process lifecycle ─────────────────────────────────────────────────────
    async def start(self) -> None:
        cmd = self._resolve_command(self.command)
        full_env = {**os.environ, **self.env}
        logger.info(f"[MCP] Launching '{self.name}': {cmd} {' '.join(self.args)}")
        self._proc = await asyncio.create_subprocess_exec(
            cmd, *self.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=full_env,
        )
        self._reader_task = asyncio.create_task(self._read_loop(), name=f"mcp-read-{self.name}")
        await self._initialize()
        await self._discover_tools()

    @staticmethod
    def _resolve_command(command: str) -> str:
        """Resolve a command to an executable path (handles npx → npx.cmd on Windows)."""
        return (
            shutil.which(command)
            or shutil.which(f"{command}.cmd")
            or shutil.which(f"{command}.exe")
            or command
        )

    async def stop(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()

    # ── JSON-RPC plumbing ─────────────────────────────────────────────────────
    async def _read_loop(self) -> None:
        assert self._proc and self._proc.stdout
        try:
            while True:
                raw = await self._proc.stdout.readline()
                if not raw:
                    break
                line = raw.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except Exception:
                    continue
                if not isinstance(msg, dict):
                    continue
                mid = msg.get("id")
                if mid is not None and ("result" in msg or "error" in msg):
                    fut = self._pending.pop(mid, None)
                    if fut and not fut.done():
                        if "error" in msg:
                            fut.set_exception(MCPError(str(msg["error"])))
                        else:
                            fut.set_result(msg["result"])
                # Server-initiated requests/notifications are ignored for now.
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"[MCP] '{self.name}' reader stopped: {e}")

    async def _write(self, msg: dict) -> None:
        assert self._proc and self._proc.stdin
        self._proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
        await self._proc.stdin.drain()

    async def _request(self, method: str, params: Optional[dict] = None, timeout: float = 30) -> Any:
        self._next_id += 1
        rid = self._next_id
        msg: dict = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            msg["params"] = params
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[rid] = fut
        await self._write(msg)
        return await asyncio.wait_for(fut, timeout=timeout)

    async def _notify(self, method: str, params: Optional[dict] = None) -> None:
        msg: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        await self._write(msg)

    # ── MCP protocol ──────────────────────────────────────────────────────────
    async def _initialize(self) -> None:
        await self._request("initialize", {
            "protocolVersion": _PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "jarvis", "version": "0.1.0"},
        })
        await self._notify("notifications/initialized")

    async def _discover_tools(self) -> None:
        result = await self._request("tools/list")
        self.tools = result.get("tools", []) if isinstance(result, dict) else []

    async def call_tool(self, tool_name: str, arguments: Optional[dict] = None) -> str:
        result = await self._request(
            "tools/call",
            {"name": tool_name, "arguments": arguments or {}},
            timeout=120,
        )
        return self._extract_text(result)

    @staticmethod
    def _extract_text(result: Any) -> str:
        if not isinstance(result, dict):
            return str(result)
        prefix = "Tool error: " if result.get("isError") else ""
        parts: list[str] = []
        for block in result.get("content", []):
            if isinstance(block, dict):
                parts.append(block.get("text", "") if block.get("type") == "text" else json.dumps(block))
            else:
                parts.append(str(block))
        return prefix + ("\n".join(p for p in parts if p) or "Done.")


class MCPManager:
    """Starts configured MCP servers and registers their tools into the registry."""

    def __init__(self, config_path: Path = CONFIG_PATH):
        self.config_path = config_path
        self._clients: Dict[str, MCPClient] = {}

    def _load_servers(self) -> Dict[str, dict]:
        if not self.config_path.exists():
            return {}
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            return data.get("mcpServers", {})
        except Exception as e:
            logger.warning(f"[MCP] Could not read {self.config_path}: {e}")
            return {}

    async def start_all(self, only: Optional[list] = None, per_server_timeout: float = 60) -> None:
        servers = self._load_servers()
        enabled = {n: c for n, c in servers.items() if not c.get("disabled")}
        if only is not None:
            enabled = {n: c for n, c in enabled.items() if n in only}
        if not enabled:
            logger.info("[MCP] No MCP servers selected to start (connect on demand).")
            return
        logger.info(f"[MCP] Starting {len(enabled)} server(s): {', '.join(enabled)}")
        await asyncio.gather(
            *(self._safe_start(n, c, per_server_timeout) for n, c in enabled.items()),
            return_exceptions=True,
        )
        total = sum(len(c.tools) for c in self._clients.values())
        logger.success(f"[MCP] {len(self._clients)} server(s) online, {total} tools registered.")

    async def _safe_start(self, name: str, cfg: dict, timeout: float) -> None:
        try:
            await asyncio.wait_for(self.start_server(name, cfg), timeout=timeout)
        except Exception as e:
            logger.warning(f"[MCP] Could not start '{name}': {e}")

    async def start_server(self, name: str, cfg: dict) -> int:
        if name in self._clients:
            return len(self._clients[name].tools)
        client = MCPClient(name, cfg.get("command", "npx"), cfg.get("args", []), cfg.get("env"))
        await client.start()
        self._clients[name] = client
        self._register_tools(name, client)
        logger.success(f"[MCP] '{name}' online with {len(client.tools)} tools.")
        return len(client.tools)

    def _register_tools(self, server_name: str, client: MCPClient) -> None:
        for t in client.tools:
            orig = t.get("name", "")
            if not orig:
                continue
            tool_name = f"{server_name}_{orig}"
            desc = t.get("description") or f"{orig} (via {server_name} MCP server)"
            params = self._schema_to_params(t.get("inputSchema", {}))

            async def _call(_client=client, _orig=orig, **kwargs):
                return await _client.call_tool(_orig, kwargs)

            registry.register_external(tool_name, desc, f"mcp:{server_name}", params, _call)

    @staticmethod
    def _schema_to_params(schema: Any) -> List[ToolParameter]:
        if not isinstance(schema, dict):
            return []
        props = schema.get("properties", {}) or {}
        required = set(schema.get("required", []) or [])
        params: List[ToolParameter] = []
        for pname, pdef in props.items():
            pdef = pdef if isinstance(pdef, dict) else {}
            params.append(ToolParameter(
                name=pname,
                param_type=pdef.get("type", "string"),
                description=pdef.get("description", pname),
                required=pname in required,
            ))
        return params

    def live_tools(self) -> Dict[str, List[str]]:
        return {name: [t.get("name", "") for t in c.tools] for name, c in self._clients.items()}

    async def stop_all(self) -> None:
        for client in list(self._clients.values()):
            try:
                await client.stop()
            except Exception:
                pass
        self._clients.clear()


# Process-wide singleton
mcp_manager = MCPManager()


# ─── Agent-exposed MCP control tools ──────────────────────────────────────────

@register_tool(
    name="list_mcp_tools",
    description="List the live tools currently provided by connected MCP servers (browser automation, web search, etc.).",
    category="mcp",
)
async def list_mcp_tools() -> str:
    """Report connected MCP servers and their available tools."""
    live = mcp_manager.live_tools()
    if not live:
        return "No MCP servers are currently connected. Ask me to connect one, like 'connect the playwright server'."
    lines = [f"{name} ({', '.join(tools) or 'no tools'})" for name, tools in live.items()]
    return "Connected MCP servers: " + " | ".join(lines)


@register_tool(
    name="connect_mcp_server",
    description="Start and connect a configured MCP server by name and register its tools at runtime (e.g. 'playwright' for browser automation, 'tavily' for web search, 'github').",
    category="mcp",
)
async def connect_mcp_server(name: str) -> str:
    """Connect a configured MCP server on demand."""
    servers = mcp_manager._load_servers()
    cfg = servers.get(name)
    if not cfg:
        available = ", ".join(servers.keys()) or "none"
        return f"No MCP server named '{name}' is configured. Available: {available}."
    try:
        count = await mcp_manager.start_server(name, cfg)
        return f"Connected the '{name}' MCP server with {count} tools ready."
    except Exception as e:
        return f"Failed to connect MCP server '{name}': {e}"
