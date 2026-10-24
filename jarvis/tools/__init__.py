"""
J.A.R.V.I.S. — Extensible Tool Ecosystem for Windows
Initializes the tool registry, registers all core automation modules,
and auto-discovers custom plugins.
"""
from pathlib import Path
from jarvis.tools.registry import registry, register_tool
from jarvis.tools import os_control
from jarvis.tools import process_control
from jarvis.tools import gui_control
from jarvis.tools import file_control
from jarvis.tools import shell_control
from jarvis.tools import web_control
from jarvis.tools import browser_tool
from jarvis.tools import mcp_bridge
from jarvis.core import memory

# Auto-discover plugins dynamically from jarvis/tools/plugins/
PLUGINS_DIR = Path(__file__).parent / "plugins"
if PLUGINS_DIR.exists():
    registry.auto_discover_plugins(PLUGINS_DIR)

__all__ = ["registry", "register_tool"]
