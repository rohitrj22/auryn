"""Auryn — a FalkorDB-backed memory engine for AI agents.

Three kinds of memory, a history that survives restarts, shared state agents
hand between each other, and one isolated graph per tenant.
"""

from .models import (
    EPISODIC,
    PROCEDURAL,
    SEMANTIC,
    AurynError,
    Handoff,
    InvalidTenant,
    MemoryRecord,
    Provenance,
    Session,
    Stats,
    StoreUnavailable,
    TaskContext,
    Turn,
)
from .memory import Memory
from .store import Store

__version__ = "0.1.0"

__all__ = [
    "Memory", "Store",
    "EPISODIC", "SEMANTIC", "PROCEDURAL",
    "MemoryRecord", "Session", "Turn", "Handoff", "TaskContext", "Provenance", "Stats",
    "AurynError", "StoreUnavailable", "InvalidTenant",
]
