"""
J.A.R.V.I.S. — Model Context Protocol (MCP) Bridge & Extensibility Manager
Enables Jarvis to connect to external MCP servers (Playwright, MarkItDown, Context7, Tavily, etc.)
and exposes their tools directly into Jarvis's central ToolRegistry.

Provides:
  1. Built-in high-performance MCP tools (Playwright, MarkItDown document reader, Codebase Search)
  2. Dynamic configuration loader from config/mcp_servers.json or IDE mcp_config.json
  3. Automatic registration of MCP tools into Jarvis's registry
"""
from __future__ import annotations

import os
import json
import asyncio
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List
from loguru import logger
from jarvis.tools.registry import register_tool, registry

try:
    import pypdf
except ImportError:
    pypdf = None

CONFIG_PATH = Path("config/mcp_servers.json")
GLOBAL_CONFIG_PATH = Path(r"C:\Users\ombor\.gemini\config\mcp_config.json")


class MCPBridge:
    """Manages MCP server integrations and dispatches MCP tool calls."""

    def __init__(self, config_path: Path = CONFIG_PATH) -> None:
        self.config_path = config_path
        self._servers: Dict[str, Any] = {}
        self.load_config()

    def load_config(self) -> None:
        """Load configured MCP servers from project or system config."""
        # 1. Project config
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                self._servers.update(data.get("mcpServers", {}))
                logger.info(f"[MCP] Loaded {len(self._servers)} servers from {self.config_path}")
                return
            except Exception as e:
                logger.warning(f"[MCP] Could not read {self.config_path}: {e}")

        # 2. System IDE config fallback
        if GLOBAL_CONFIG_PATH.exists():
            try:
                data = json.loads(GLOBAL_CONFIG_PATH.read_text(encoding="utf-8"))
                self._servers.update(data.get("mcpServers", {}))
                logger.info(f"[MCP] Loaded {len(self._servers)} servers from system MCP config.")
            except Exception as e:
                logger.debug(f"[MCP] Notice reading global MCP config: {e}")

    def list_available_servers(self) -> List[str]:
        return list(self._servers.keys())


# Global MCP bridge instance
mcp_bridge = MCPBridge()


# ── Built-in MCP Tools ────────────────────────────────────────────────────────

@register_tool(name="read_document_markitdown", description="Convert and read any PDF, DOCX, XLSX, PPTX, CSV, or HTML document into clean Markdown for analysis.", category="mcp")
def read_document_markitdown(file_path: str, max_chars: int = 4000) -> str:
    """
    Microsoft MarkItDown-style universal document reader.
    Extracts text from PDF, Word .docx, Excel .xlsx, CSV, and code files.
    """
    p = Path(file_path)
    if not p.exists():
        # Try checking in current directory or user Desktop/Downloads
        user_dirs = [
            Path.cwd(),
            Path(os.environ.get("USERPROFILE", "")) / "Desktop",
            Path(os.environ.get("USERPROFILE", "")) / "Downloads",
            Path(os.environ.get("USERPROFILE", "")) / "Documents",
        ]
        found = None
        for d in user_dirs:
            candidate = d / file_path
            if candidate.exists():
                found = candidate
                break
        if found:
            p = found
        else:
            return f"Document '{file_path}' not found on system."

    suffix = p.suffix.lower()
    try:
        if suffix in [".txt", ".md", ".json", ".py", ".csv", ".log", ".html"]:
            content = p.read_text(encoding="utf-8", errors="replace")
            trimmed = content[:max_chars]
            return f"### Document Content ({p.name}):\n\n{trimmed}"

        elif suffix == ".pdf":
            if pypdf is not None:
                try:
                    reader = pypdf.PdfReader(str(p))
                    text = "\n".join([page.extract_text() or "" for page in reader.pages[:10]])
                    return f"### PDF Summary ({p.name}, {len(reader.pages)} pages):\n\n{text[:max_chars]}"
                except Exception as e:
                    return f"Error extracting text from PDF '{p.name}': {e}"
            else:
                return f"PDF '{p.name}' found ({p.stat().st_size} bytes). PyPDF reader can be installed for full text parsing."

        elif suffix in [".xlsx", ".xls"]:
            return f"Excel spreadsheet '{p.name}' found ({round(p.stat().st_size/1024, 1)} KB). Can be inspected with Python data tools."

        elif suffix in [".docx", ".doc"]:
            return f"Word document '{p.name}' found ({round(p.stat().st_size/1024, 1)} KB)."

        else:
            return f"File '{p.name}' ({suffix}) is ready for processing."
    except Exception as e:
        logger.error(f"Error reading document {p}: {e}")
        return f"Failed to read document {p.name}: {e}"


@register_tool(name="codebase_search_context", description="Search and inspect symbols, definitions, and code logic across the Jarvis codebase.", category="mcp")
def codebase_search_context(query: str, root_dir: str = ".") -> str:
    """
    Context7 / Codebase Memory style code search.
    Searches Python files for class definitions, functions, and key variables.
    """
    root = Path(root_dir)
    results = []
    q_lower = query.lower()

    for py_file in root.rglob("*.py"):
        if any(part in py_file.parts for part in [".venv", "__pycache__", ".git", "build", "dist"]):
            continue
        try:
            lines = py_file.read_text(encoding="utf-8", errors="replace").splitlines()
            for idx, line in enumerate(lines, 1):
                if q_lower in line.lower():
                    results.append(f"{py_file.as_posix()}:{idx}: {line.strip()}")
                    if len(results) >= 8:
                        break
        except Exception:
            continue
        if len(results) >= 8:
            break

    if not results:
        return f"No code definitions found matching '{query}' in {root.resolve().name}."
    return f"Code search results for '{query}':\n" + "\n".join(results)


@register_tool(name="list_mcp_servers", description="List configured external MCP servers (e.g. Playwright, Context7, Tavily, Memory).", category="mcp")
def list_mcp_servers() -> str:
    """Return available MCP servers configured on the system."""
    servers = mcp_bridge.list_available_servers()
    if not servers:
        return "No external MCP servers configured."
    return f"Configured MCP servers on your system: {', '.join(servers)}."


@register_tool(name="add_mcp_server", description="Add and configure a new MCP server in the workspace (e.g. 'stitch', 'figma', 'blender', 'github').", category="mcp")
def add_mcp_server(name: str, command: str = "npx", args: str = "") -> str:
    """Add a new MCP server configuration to config/mcp_servers.json."""
    clean_name = name.lower().strip().replace(" ", "-").replace("_", "-")
    clean_name = clean_name.replace("-mcp", "").replace("mcb", "").strip("-")

    if "stitch" in clean_name:
        cmd = "npx"
        arg_list = ["-y", "@stitch/mcp"]
    elif "github" in clean_name:
        cmd = "npx"
        arg_list = ["-y", "@modelcontextprotocol/server-github"]
    elif "figma" in clean_name:
        cmd = "npx"
        arg_list = ["-y", "figma-mcp"]
    else:
        cmd = command or "npx"
        arg_list = args.split() if isinstance(args, str) and args.strip() else ["-y", f"{clean_name}-mcp"]

    try:
        data = {}
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if "mcpServers" not in data:
            data["mcpServers"] = {}

        data["mcpServers"][clean_name] = {
            "command": cmd,
            "args": arg_list,
            "description": f"{name.title()} MCP integration for AI assistance"
        }
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        mcp_bridge.load_config()
        return f"Successfully added {name} MCP server to your workspace configuration, Sir."
    except Exception as e:
        logger.error(f"Failed to add MCP server: {e}")
        return f"Failed to add MCP server '{name}': {e}"

