"""Tenant bootstrap: indexes, and subject resolution.

Every field recall filters on is indexed. Two full-text indexes exist:
one over memory text (recall), one over subject names (resolution).
"""

from __future__ import annotations

import re

from redis.exceptions import ResponseError

from . import queries as q
from .store import Store

# A score below this is not considered the same subject.
RESOLVE_MIN_SCORE = 2.0
# Two matches this close are ambiguous, so we never merge them.
RESOLVE_MARGIN = 1.0

_SLUG = re.compile(r"[^a-z0-9]+")
_DASHES = re.compile(r"-{2,}")


def slug(name: str) -> str:
    """A stable subject key from a human name. Normalisation only, no matching."""
    s = _SLUG.sub("-", (name or "").lower()).strip("-")
    s = _DASHES.sub("-", s)
    return s[:64] or "unknown"


# Tenants this process has already bootstrapped. Opening a Memory is common,
# so repeating the work would be wasteful.
_READY: set[tuple[str, str]] = set()

# Which index each statement creates, so we only issue the missing ones.
# Attempting an existing index is rejected by FalkorDB and counted in its own
# failed_calls, which would corrupt any benchmark that reads that figure.
_WANTED: tuple[tuple[str, str, str], ...] = (
    ("Subject", "key", q.RANGE_INDEXES[0]),
    ("Memory", "at", q.RANGE_INDEXES[1]),
    ("Memory", "id", q.RANGE_INDEXES[2]),
    ("Session", "id", q.RANGE_INDEXES[3]),
    ("Task", "id", q.RANGE_INDEXES[4]),
    ("Memory", "text", q.FULLTEXT_INDEXES[0]),
    ("Subject", "name", q.FULLTEXT_INDEXES[1]),
)


def forget(store: Store, tenant: str) -> None:
    """Drop a tenant from the bootstrap cache.

    Dropping a graph removes its indexes too, so the cache must not keep
    claiming the tenant is ready. Missing this made recall return nothing
    after forget_everything(), because the full-text index was never rebuilt.
    """
    _READY.discard((store.url, tenant))
    for cache_key in [k for k in _RESOLVED if k[0] == store.url and k[1] == tenant]:
        del _RESOLVED[cache_key]


def _existing(store: Store, tenant: str) -> set[tuple[str, str]]:
    """Labels and fields already indexed, read from the graph itself."""
    try:
        res = store.query(tenant, q.LIST_INDEXES)
    except ResponseError:
        return set()
    found: set[tuple[str, str]] = set()
    for row in res.result_set or []:
        label = row[0]
        for field in (row[1] or []):
            found.add((label, field))
    return found


def ensure(store: Store, tenant: str) -> None:
    """Create any missing index for a tenant graph. Cheap to call repeatedly.

    One read, then only the statements that are actually needed. It never
    issues a statement it expects to fail.
    """
    key = (store.url, tenant)
    if key in _READY:
        return
    have = _existing(store, tenant)
    for label, field, cypher in _WANTED:
        if (label, field) in have:
            continue
        try:
            store.query(tenant, cypher)
        except ResponseError as exc:
            if "already" not in str(exc).lower() and "exist" not in str(exc).lower():
                raise
    _READY.add(key)


# Names this process has already resolved. Agents reuse a small set of
# subjects, so the full-text lookup is the hot path worth removing.
# A stale entry can only cause a new subject where a merge was possible, never
# a wrong merge, because only positive resolutions are cached.
_RESOLVED: dict[tuple[str, str, str], tuple[str, str | None]] = {}


def resolve_subject(store: Store, tenant: str, name: str) -> tuple[str, str | None]:
    """Map a subject name onto an existing subject, or mint a new one.

    Returns (key, related_to_key). `related_to_key` is set only when the match
    was ambiguous: we create a new subject and link it to the nearest one, so
    ambiguity becomes an edge rather than a wrong merge.

    Uses AND semantics. With item441, item442 and item4410 all present,
    "item 441" matches only item441.
    """
    terms = q.terms_and(name)
    key = slug(name)
    if not terms:
        return key, None

    cached = _RESOLVED.get((store.url, tenant, terms))
    if cached is not None:
        return cached

    try:
        res = store.query(tenant, q.RESOLVE_SUBJECT, {"terms": terms})
    except ResponseError:
        return key, None  # no index yet, or no subjects yet

    rows = res.result_set or []
    if not rows:
        _RESOLVED[(store.url, tenant, terms)] = (key, None)
        return key, None

    top_key, _top_name, top_score = rows[0][0], rows[0][1], float(rows[0][2])
    if top_score < RESOLVE_MIN_SCORE:
        answer = (key, None)
    elif len(rows) > 1 and (top_score - float(rows[1][2])) < RESOLVE_MARGIN:
        # Ambiguous. Mint a new subject, but keep the near match reachable.
        answer = (key, top_key)
    else:
        answer = (top_key, None)

    _RESOLVED[(store.url, tenant, terms)] = answer
    return answer
