"""Live integration probe — Phase 3: Playwright MCP browser automation."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
logger.remove()
logger.add(sys.stderr, level="WARNING")

import jarvis.tools  # noqa
from jarvis.tools.registry import registry
from jarvis.tools.mcp_runtime import mcp_manager


async def call(name, **kw):
    r = await registry.execute(name, **kw)
    out = r.get("result", r.get("message", r))
    s = str(out)
    print(f"  {name}({kw}) -> {s[:200]}")
    return out


async def main():
    print("== starting playwright MCP server (npx, may take a bit) ==")
    await mcp_manager.start_all(only=["playwright"], per_server_timeout=120)
    tools = sorted(t.name for t in registry.list_tools() if t.category == "mcp:playwright")
    print(f"  registered {len(tools)} playwright tools")
    nav = next((t for t in tools if t.endswith("browser_navigate")), None)
    newtab = next((t for t in tools if "tab" in t and ("new" in t or "open" in t)), None)
    tablist = next((t for t in tools if t.endswith("tab_list") or t.endswith("browser_tabs")), None)
    print(f"  nav={nav} newtab={newtab} tablist={tablist}")

    if nav:
        print("== navigate to example.com ==")
        await call(nav, url="https://example.com")
        print("== navigate to wikipedia.org ==")
        await call(nav, url="https://www.wikipedia.org")

    # Tabs API name varies by MCP version; try the common ones.
    for t in tools:
        if t.endswith("browser_tabs"):
            print(f"== {t} list ==")
            await call(t, action="list")
            print(f"== {t} new ==")
            await call(t, action="new")

    print("== snapshot (title/url) ==")
    snap = next((t for t in tools if t.endswith("browser_snapshot")), None)
    if snap:
        await call(snap)

    print("== closing browser ==")
    closer = next((t for t in tools if t.endswith("browser_close")), None)
    if closer:
        await call(closer)

    await mcp_manager.stop_all()
    print("== done ==")


if __name__ == "__main__":
    asyncio.run(main())
