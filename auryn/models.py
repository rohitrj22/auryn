"""Value types for Auryn. No business vocabulary belongs in this module."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# The three memory kinds. The public name maps to the graph label.
EPISODIC = "Event"
SEMANTIC = "Fact"
PROCEDURAL = "Procedure"

KINDS = (EPISODIC, SEMANTIC, PROCEDURAL)

# A memory longer than this is stored truncated, and the truncation is recorded.
MAX_TEXT = 4000

# A tenant name becomes a graph name, so it must be safe as one.
TENANT_MAX = 128
_TENANT_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")


class AurynError(Exception):
    """Base class for every error this engine raises."""


class StoreUnavailable(AurynError):
    """FalkorDB could not be reached. The engine never falls back to another store."""


class InvalidTenant(AurynError):
    """The tenant name is not safe to use as a graph name."""


def validate_tenant(tenant: str) -> str:
    """Return the tenant unchanged, or raise before any query runs."""
    if not tenant or not isinstance(tenant, str):
        raise InvalidTenant("tenant must be a non-empty string")
    if len(tenant) > TENANT_MAX:
        raise InvalidTenant(f"tenant longer than {TENANT_MAX} characters")
    bad = sorted(set(tenant) - _TENANT_OK)
    if bad:
        raise InvalidTenant(f"tenant contains unsafe characters: {''.join(bad)!r}")
    return tenant


def validate_kind(kind: str) -> str:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
    return kind


def clamp_text(text: str) -> tuple[str, bool]:
    """Return the text and whether it was truncated. Truncation is never silent."""
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    if len(text) <= MAX_TEXT:
        return text, False
    return text[:MAX_TEXT], True


@dataclass(frozen=True)
class MemoryRecord:
    id: str
    kind: str
    text: str
    at: int
    agent: str
    session_id: str | None = None
    subject_key: str | None = None
    derived: bool = False
    superseded: bool = False
    truncated: bool = False
    trigger: str | None = None
    hops: int | None = None
    score: float | None = None


@dataclass(frozen=True)
class Turn:
    id: str
    role: str
    text: str
    idx: int
    at: int


@dataclass(frozen=True)
class Session:
    id: str
    started_at: int
    ended_at: int | None = None
    agent: str | None = None


@dataclass(frozen=True)
class Handoff:
    id: str
    task: str
    from_agent: str
    to_agent: str
    at: int
    note: str | None = None


@dataclass(frozen=True)
class TaskContext:
    """Everything a receiving agent needs, from a tenant and a task id alone."""

    task: str
    title: str | None
    state: str
    owner: str | None
    handed_from: str | None
    memories: list[MemoryRecord] = field(default_factory=list)


@dataclass(frozen=True)
class Provenance:
    """Why a memory exists. The read path for FR-011 and FR-016a."""

    memory_id: str
    kind: str
    text: str
    agent: str
    session_id: str | None
    at: int
    derived: bool
    derived_from: list[MemoryRecord] = field(default_factory=list)
    supersedes: list[MemoryRecord] = field(default_factory=list)


@dataclass(frozen=True)
class Stats:
    """FalkorDB's own figures, returned unchanged. The engine keeps no counters."""

    graph_count: int
    used_memory_bytes: int
    latency_percentiles: dict[str, dict[str, float]]
    command_stats: dict[str, dict[str, Any]]
    config: dict[str, Any]
