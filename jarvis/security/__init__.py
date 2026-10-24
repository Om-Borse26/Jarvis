"""
J.A.R.V.I.S. — Security Layer
Encrypted secrets vault, action auditing, and risk classification.

Importing this package registers the vault tools into the central registry.
"""
from jarvis.security import vault  # noqa: F401  (registers vault tools)
from jarvis.security import audit  # noqa: F401
from jarvis.security import consent  # noqa: F401

__all__ = ["vault", "audit", "consent"]
