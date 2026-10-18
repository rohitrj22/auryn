"""Dropping a tenant must rebuild its indexes on the next use.

A bootstrap cache once kept claiming a dropped tenant was ready, so its
full-text index was never rebuilt and recall silently returned nothing.
"""

from __future__ import annotations

from auryn import SEMANTIC, Memory


def test_recall_works_after_forget_everything() -> None:
    mem = Memory(tenant="test-rebootstrap")
    mem.remember(SEMANTIC, "a distinctive marker phrase", agent="t", subject="marker")
    assert mem.recall("distinctive marker"), "baseline recall must work"

    mem.forget_everything()
    again = Memory(tenant="test-rebootstrap")
    again.remember(SEMANTIC, "a distinctive marker phrase", agent="t", subject="marker")

    assert again.recall("distinctive marker"), (
        "recall returned nothing after the graph was dropped and rebuilt; "
        "the full-text index was probably not recreated"
    )
    again.forget_everything()
