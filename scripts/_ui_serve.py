"""Serve the UI with seeded reminders so the dashboard/island can be inspected."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
logger.remove()
logger.add(sys.stderr, level="WARNING")

from jarvis.core.scheduler import scheduler, set_reminder, schedule_meeting
from jarvis.ui.server import ControlServer

# Seed a few reminders/meetings (idempotent enough for a quick look).
print(set_reminder("Call the dentist", "in 2 hours"))
print(set_reminder("Submit the expense report", "in 45 minutes", "high"))
print(schedule_meeting("Team standup", "in 30 minutes", 10))

print("JOBS:", scheduler.list_jobs())

srv = ControlServer(8787)
assert srv.start(), "server failed to bind"
print("SERVER_READY on http://127.0.0.1:8787")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    pass
