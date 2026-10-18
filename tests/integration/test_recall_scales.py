"""Recall must not slow down as a tenant remembers more.

Recall once applied its LIMIT after the traversal, so it expanded every
full-text match before trimming. Cost grew with total memory: 14 ms at 50
matches, 312 ms at 800, and a query timeout at 2000. Capping the seeds before
the expansion made the work independent of how much is stored.

This test fails if that regression returns.
"""

from __future__ import annotations

import statistics

from auryn import SEMANTIC, Memory

TENANT = "test-recall-scales"
# Generous, so the test is about the shape of the curve, not the machine.
MAX_MS = 25.0
MAX_GROWTH = 6.0


def _median_ms(mem: Memory, query: str, runs: int = 7) -> float:
    import time

    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        mem.recall(query)
        times.append((time.perf_counter() - t0) * 1000)
    return statistics.median(times)


def test_recall_cost_does_not_grow_with_total_memory() -> None:
    mem = Memory(tenant=TENANT)
    mem.forget_everything()
    mem = Memory(tenant=TENANT)

    for i in range(100):
        mem.remember(SEMANTIC, f"a fact about a thing number {i}",
                     agent="t", subject=f"subject-{i % 5}")
    small = _median_ms(mem, "fact thing")

    for i in range(100, 1200):
        mem.remember(SEMANTIC, f"a fact about a thing number {i}",
                     agent="t", subject=f"subject-{i % 5}")
    large = _median_ms(mem, "fact thing")

    mem.forget_everything()

    assert large < MAX_MS, (
        f"recall took {large:.1f} ms at 1200 memories, over the {MAX_MS} ms budget; "
        "the seed cap before the traversal has probably been removed"
    )
    assert large < small * MAX_GROWTH, (
        f"recall grew {large / max(small, 0.01):.1f}x from 100 to 1200 memories "
        f"({small:.1f} ms -> {large:.1f} ms); cost must stay roughly flat"
    )


def test_recall_still_respects_its_cap() -> None:
    mem = Memory(tenant=TENANT)
    mem.forget_everything()
    mem = Memory(tenant=TENANT, recall_cap=20)
    for i in range(200):
        mem.remember(SEMANTIC, f"a fact about a thing number {i}",
                     agent="t", subject=f"subject-{i % 5}")
    assert len(mem.recall("fact thing")) == 20
    assert len(mem.recall("fact thing", limit=5)) == 5
    mem.forget_everything()
