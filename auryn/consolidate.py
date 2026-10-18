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


def derive_now(
    store: Store,
    tenant: str,
    subject: str,
    *,
    count: int,
    at: int,
    session_id: str | None,
    agent: str = "auryn",
) -> str | None:
    """Write the derived fact, given a count already in hand.

    Deriving is rare, so this path may spend a query fetching the evidence
    ids. The common write must not pay for it.
    """
    res = store.query(tenant, q.COUNT_EVENTS_FOR_SUBJECT,
                      {"subject": subject, "max": MAX_EVIDENCE}, read_only=True)
    event_ids = list(res.result_set[0][1] or []) if res.result_set else []
    fid = derived_id(subject)
    store.query(
        tenant, q.DERIVE_FACT,
        {"id": fid, "text": f"{count} separate events concern {subject}", "at": at,
         "subject": subject, "agent": agent, "session_id": session_id,
         "event_ids": event_ids},
    )
    return fid
