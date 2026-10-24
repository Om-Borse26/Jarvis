"""
J.A.R.V.I.S. — Tiered Memory Package
  L2 Working  (working.py)   — live, in-RAM "now" context
  L3 Episodic (episodic.py)  — durable log of past interactions and outcomes
  L4 Semantic (semantic.py)  — meaning-based long-term recall of facts/preferences

(L1 conversation turns live in the pipeline; the user profile/facts live in
jarvis/core/memory.py.)
"""
from jarvis.memory.working import working_memory
from jarvis.memory.episodic import episodic_memory  # noqa: F401 (registers recall tool)
from jarvis.memory.semantic import semantic_memory
from jarvis.memory.shared_bus import shared_bus  # noqa: F401 (registers Eve bus tools)

__all__ = ["working_memory", "episodic_memory", "semantic_memory", "shared_bus"]
