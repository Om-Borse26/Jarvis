"""
Island freeze probe (testing only).

Starts the control server, launches the real Island window as a subprocess, then
drives mode changes (mini → tools → dashboard → collapsed) exactly like the voice
commands do. The Island posts a heartbeat every 2s; if the window froze, the
heartbeats would stop. We pass only if heartbeats keep flowing AFTER each change.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis.ui.server import ControlServer
from jarvis.ui.state import ui_directive

srv = ControlServer(8787)
assert srv.start(), "control server failed to bind"

proc = subprocess.Popen([sys.executable, "-m", "jarvis.ui.island"], cwd=str(Path.cwd()))
print("launched island pid", proc.pid)

schedule = {5: "mini", 8: "tools", 11: "dashboard", 14: "collapsed"}
beats = []
ok = True
try:
    for t in range(0, 18):
        if t in schedule:
            ui_directive.set(mode=schedule[t], forward=(schedule[t] != "collapsed"))
            print(f"[t={t:2}s] -> pushed mode={schedule[t]}")
        alive = ui_directive.is_alive(within=3.5)
        beats.append(alive)
        # Ignore the first 3s while the window boots.
        if t >= 4 and not alive:
            print(f"[t={t:2}s] !! no heartbeat (possible freeze)")
            ok = False
        else:
            print(f"[t={t:2}s] heartbeat={'yes' if alive else 'booting'} alive={proc.poll() is None}")
        if proc.poll() is not None:
            print("!! island process exited early:", proc.returncode)
            ok = False
            break
        time.sleep(1)
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    srv.stop()

print("\nRESULT:", "PASS (no freeze, window stayed responsive)" if ok else "FAIL")
sys.exit(0 if ok else 1)
