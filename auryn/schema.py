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


def ensure(store: Store, tenant: str) -> None:
    """Create every index for a tenant graph. Safe to call repeatedly."""
    for cypher in q.RANGE_INDEXES + q.FULLTEXT_INDEXES:
        try:
            store.query(tenant, cypher)
        except ResponseError as exc:
            # FalkorDB reports an existing index as an error. That is success here.
            if "already" not in str(exc).lower() and "exist" not in str(exc).lower():
                raise


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

    try:
        res = store.query(tenant, q.RESOLVE_SUBJECT, {"terms": terms})
    except ResponseError:
        return key, None  # no index yet, or no subjects yet

    rows = res.result_set or []
    if not rows:
        return key, None

    top_key, _top_name, top_score = rows[0][0], rows[0][1], float(rows[0][2])
    if top_score < RESOLVE_MIN_SCORE:
        return key, None

    if len(rows) > 1:
        second_score = float(rows[1][2])
        if (top_score - second_score) < RESOLVE_MARGIN:
            # Ambiguous. Mint a new subject, but keep the near match reachable.
            return key, top_key

    return top_key, None
