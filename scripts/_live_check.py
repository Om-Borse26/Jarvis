"""Live integration probe — Phase 1: system + process tools (reversible)."""
from __future__ import annotations

import asyncio
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
logger.remove()
logger.add(sys.stderr, level="WARNING")

import jarvis.tools  # noqa
from jarvis.tools.registry import registry


async def call(name, **kw):
    r = await registry.execute(name, **kw)
    out = r.get("result", r.get("message", r))
    print(f"  {name}({kw}) -> {out}")
    return out


async def main():
    print("== get_volume ==")
    v = await call("get_volume")
    m = re.search(r"(\d+)", str(v))
    original = int(m.group(1)) if m else None

    print("== set_volume 25 ==")
    await call("set_volume", percent=25)
    await call("get_volume")

    print("== change_volume_relative +10 ==")
    await call("change_volume_relative", delta_percent=10)
    await call("get_volume")

    if original is not None:
        print(f"== restoring volume to {original} ==")
        await call("set_volume", percent=original)

    print("== get_current_active_window ==")
    await call("get_current_active_window")

    print("== get_hardware_metrics ==")
    await call("get_hardware_metrics")

    print("== list_active_apps ==")
    await call("list_active_apps")

    print("== launch notepad (background) ==")
    await call("launch_application", app_name="notepad", background=True)
    time.sleep(2.5)
    import psutil
    running = any((p.info["name"] or "").lower() == "notepad.exe"
                  for p in psutil.process_iter(["name"]))
    print(f"  notepad running: {running}")

    print("== focus_application notepad ==")
    await call("focus_application", app_name="notepad")

    print("== kill notepad ==")
    await call("kill_process", process_name="notepad")
    time.sleep(1)
    running2 = any((p.info["name"] or "").lower() == "notepad.exe"
                   for p in psutil.process_iter(["name"]))
    print(f"  notepad running after kill: {running2}")


if __name__ == "__main__":
    asyncio.run(main())
