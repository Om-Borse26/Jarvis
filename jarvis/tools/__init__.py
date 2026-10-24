"""
J.A.R.V.I.S. — Extensible Tool Ecosystem for Windows
Initializes the tool registry, registers all core automation modules,
and auto-discovers custom plugins.

Tool Tiers:
  Tier 1: Native Tools — instant OS commands (os_control, process_control)
  Tier 2: Computer Use — screenshot + mouse + keyboard (computer_use)
  Tier 3: Browser Automation — Playwright MCP (mcp_bridge)
  Tier 4: Code Generation — safe code execution (code_executor)
"""
from pathlib import Path
from jarvis.tools.registry import registry, register_tool

# ── Tier 1: Native fast-path tools ───────────────────────────────────────────
from jarvis.tools import os_control
from jarvis.tools import process_control
from jarvis.tools import gui_control
from jarvis.tools import file_control
from jarvis.tools import shell_control
from jarvis.tools import web_control
from jarvis.tools import browser_tool
from jarvis.tools import whatsapp_control

# ── Tier 2: Computer Use tools ───────────────────────────────────────────────
from jarvis.tools import computer_use

# ── Tier 3: MCP Bridge ──────────────────────────────────────────────────────
from jarvis.tools import mcp_bridge
from jarvis.tools import mcp_runtime  # real stdio MCP client + control tools

# ── Tier 4: Code execution ───────────────────────────────────────────────────
from jarvis.tools import code_executor

# ── Memory tools ─────────────────────────────────────────────────────────────
from jarvis.core import memory
from jarvis import memory as memory_layers  # noqa: F401  (L2/L3/L4 + episodic tool)

# ── Proactivity: reminders & recurring tasks ─────────────────────────────────
from jarvis.core import scheduler as scheduler_tools  # noqa: F401  (registers scheduler tools)

# ── Security: encrypted secrets vault + audit tools ──────────────────────────
from jarvis import security  # noqa: F401  (registers vault tools)

# Auto-discover plugins dynamically from jarvis/tools/plugins/
PLUGINS_DIR = Path(__file__).parent / "plugins"
if PLUGINS_DIR.exists():
    registry.auto_discover_plugins(PLUGINS_DIR)

__all__ = ["registry", "register_tool"]
