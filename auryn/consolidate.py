"""Deriving a lasting fact from repeated events.

A count rule, not a language model. So it works with no credentials and is
testable by counting.
"""

from __future__ import annotations

import hashlib

from . import queries as q
from .store import Store

MAX_EVIDENCE = 20


def derived_id(subject: str) -> str:
    """One derived fact per subject, so repeat runs update instead of multiply."""
    return "d_" + hashlib.sha1(subject.encode()).hexdigest()[:16]


def maybe_derive(
    store: Store,
    tenant: str,
    subject: str,
    *,
    threshold: int,
    at: int,
    session_id: str | None,
    agent: str = "auryn",
) -> str | None:
    """Write a derived fact when events about one subject reach the threshold.

    Returns the derived fact's id, or None when the threshold is not met.
    The fact stays linked to every event it came from, so a reader can see why.
    """
    res = store.query(tenant, q.COUNT_EVENTS_FOR_SUBJECT, {"subject": subject, "max": MAX_EVIDENCE})
    if not res.result_set:
        return None
    count, event_ids = res.result_set[0]
    if count is None or int(count) < threshold:
        return None

    fid = derived_id(subject)
    text = f"{count} separate events concern {subject}"
    store.query(
        tenant,
        q.DERIVE_FACT,
        {
            "id": fid,
            "text": text,
            "at": at,
            "subject": subject,
            "agent": agent,
            "session_id": session_id,
            "event_ids": list(event_ids or []),
        },
    )
    return fid
