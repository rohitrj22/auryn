"""FalkorDB's own instruments, read and returned unchanged.

Auryn keeps no counters of its own. Every number we publish comes from here,
so no figure is one we computed about ourselves.
"""

from __future__ import annotations

from typing import Any

from .models import Stats
from .store import Store


def _text(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def _as_mapping(raw: Any) -> dict[str, Any]:
    """FalkorDB replies either as a flat key/value list or as a list of pairs.

    GRAPH.CONFIG GET * returns pairs: [['TIMEOUT', 1000], ['CACHE_SIZE', 25], ...]
    Handle both shapes rather than assume one.
    """
    out: dict[str, Any] = {}
    if not raw:
        return out
    if all(isinstance(item, (list, tuple)) and len(item) == 2 for item in raw):
        for key, value in raw:
            out[_text(key)] = value
        return out
    for i in range(0, len(raw) - 1, 2):
        out[_text(raw[i])] = raw[i + 1]
    return out


def _percentiles(info: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Server-side p50, p99 and p99.9 per command. We never compute these."""
    out: dict[str, dict[str, float]] = {}
    for key, value in info.items():
        if not key.startswith("latency_percentiles_usec_"):
            continue
        cmd = key[len("latency_percentiles_usec_"):]
        if isinstance(value, dict):
            out[cmd] = {k: float(v) for k, v in value.items()}
        else:
            parsed: dict[str, float] = {}
            for part in str(value).split(","):
                if "=" in part:
                    k, v = part.split("=", 1)
                    parsed[k.strip()] = float(v)
            out[cmd] = parsed
    return out


def _commandstats(info: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for key, value in info.items():
        if not key.startswith("cmdstat_"):
            continue
        cmd = key[len("cmdstat_"):]
        if isinstance(value, dict):
            out[cmd] = dict(value)
        else:
            parsed: dict[str, Any] = {}
            for part in str(value).split(","):
                if "=" in part:
                    k, v = part.split("=", 1)
                    try:
                        parsed[k] = float(v) if "." in v else int(v)
                    except ValueError:
                        parsed[k] = v
            out[cmd] = parsed
    return out


# Reads go through GRAPH.RO_QUERY, writes through GRAPH.QUERY. Counting only
# one of them would miss most of the work.
_QUERY_COMMANDS = ("graph.QUERY", "GRAPH.QUERY", "graph.query",
                   "graph.RO_QUERY", "GRAPH.RO_QUERY", "graph.ro_query")


def graph_query_stats(store: Store) -> dict[str, Any]:
    """Both query command paths, summed: calls, usec_per_call, rejected, failed."""
    stats = _commandstats(store.connection.info("commandstats"))
    rows = [stats[n] for n in _QUERY_COMMANDS if n in stats]
    if not rows:
        return {}
    calls = sum(int(r.get("calls") or 0) for r in rows)
    usec = sum(float(r.get("usec") or 0.0) for r in rows)
    return {
        "calls": calls,
        "usec": usec,
        "usec_per_call": (usec / calls) if calls else 0.0,
        "rejected_calls": sum(int(r.get("rejected_calls") or 0) for r in rows),
        "failed_calls": sum(int(r.get("failed_calls") or 0) for r in rows),
        "by_command": {n: stats[n] for n in _QUERY_COMMANDS if n in stats},
    }


def graph_query_percentiles(store: Store) -> dict[str, float]:
    """Server percentiles. Prefers the write path, falls back to read-only."""
    pcts = _percentiles(store.connection.info("latencystats"))
    for name in _QUERY_COMMANDS:
        if name in pcts:
            return pcts[name]
    return {}


def used_memory(store: Store) -> int:
    return int(store.connection.info("memory")["used_memory"])


def graph_memory_usage(store: Store, tenant: str) -> dict[str, Any]:
    """Component breakdown for one graph.

    Rounds to whole megabytes, so it cannot measure a small graph. Use the
    used_memory delta for per-tenant cost, and this for the breakdown on a
    larger graph.
    """
    return _as_mapping(store.connection.execute_command("GRAPH.MEMORY", "USAGE", tenant))


def config(store: Store) -> dict[str, Any]:
    """The configuration a run executed against. Published, never assumed."""
    return _as_mapping(store.connection.execute_command("GRAPH.CONFIG", "GET", "*"))


def reset_command_stats(store: Store) -> None:
    """Zero the server counters, so a load run reports only its own work."""
    store.connection.execute_command("CONFIG", "RESETSTAT")


def read_stats(store: Store) -> Stats:
    return Stats(
        graph_count=len(store.list_graphs()),
        used_memory_bytes=used_memory(store),
        latency_percentiles=_percentiles(store.connection.info("latencystats")),
        command_stats=_commandstats(store.connection.info("commandstats")),
        config=config(store),
    )
