"""J.A.R.V.I.S. — Eve package (phone companion: shared memory + LAN sync)."""
from jarvis.eve.companion import eve
from jarvis.eve.server import EveSyncServer

__all__ = ["eve", "EveSyncServer"]
