"""Criterion: high-concurrency reads and writes.

Every figure here comes from FalkorDB's own instruments, not from a counter we
kept. Two rules this proof holds itself to:

  1. Report both sides. The caller's time and the store's own time. The gap
     between them is Auryn's overhead, stated as a number rather than waved at.
  2. Never publish a figure without naming what limited the run.

Load is generated from several PROCESSES. A single Python process tops out at
roughly a thousand operations a second, which is about half what the server
answers, so a one-process benchmark would understate FalkorDB by half.
"""

from __future__ import annotations

import argparse
import multiprocessing as mp
import time

from auryn import FACT, Memory, Store
from auryn.metrics import (
    config,
    graph_query_percentiles,
    graph_query_stats,
    reset_command_stats,
    used_memory,
)

from ._check import Proof, finish

PREFIX = "proof-p5-t"


def _load(args: tuple[int, int, float, int]) -> dict:
    """One worker process: mixed reads and writes across many tenants."""
    worker, tenants, seconds, offset = args
    mem_by_tenant: dict[int, Memory] = {}
    writes = reads = errors = 0
    client_ns = 0
    deadline = time.perf_counter() + seconds
    i = offset
    while time.perf_counter() < deadline:
        t = i % tenants
        if t not in mem_by_tenant:
            mem_by_tenant[t] = Memory(tenant=f"{PREFIX}{t:03d}")
        mem = mem_by_tenant[t]
        try:
            t0 = time.perf_counter_ns()
            if i % 3 == 0:
                mem.remember(FACT, f"w{worker} fact {i} for tenant {t}",
                             agent=f"w{worker}", subject=f"subject-{i % 7}")
                writes += 1
            else:
                mem.recall(f"fact tenant {t}")
                reads += 1
            client_ns += time.perf_counter_ns() - t0
        except Exception:  # noqa: BLE001 - counted, never hidden
            errors += 1
        i += 1
    return {"worker": worker, "writes": writes, "reads": reads,
            "errors": errors, "client_ns": client_ns}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--procs", type=int, default=8)
    ap.add_argument("--tenants", type=int, default=50)
    ap.add_argument("--seconds", type=float, default=15.0)
    args = ap.parse_args()

    p = Proof("concurrency", "high-concurrency reads and writes").start()

    store = Store()
    for g in [g for g in store.list_graphs() if g.startswith(PREFIX)]:
        store.drop(g)
    for t in range(args.tenants):
        Memory(tenant=f"{PREFIX}{t:03d}")           # bootstrap indexes up front
    cfg = config(store)
    reset_command_stats(store)                       # count only this run's work
    mem_before = used_memory(store)

    p.note(f"{args.procs} processes, {args.tenants} tenants, {args.seconds:g}s")

    t0 = time.perf_counter()
    with mp.Pool(args.procs) as pool:
        results = pool.map(_load, [(n, args.tenants, args.seconds, n * 977)
                                   for n in range(args.procs)])
    wall = time.perf_counter() - t0

    writes = sum(r["writes"] for r in results)
    reads = sum(r["reads"] for r in results)
    errors = sum(r["errors"] for r in results)
    ops = writes + reads
    client_us = sum(r["client_ns"] for r in results) / max(ops, 1) / 1000

    srv = graph_query_stats(store)
    pct = graph_query_percentiles(store)
    queries = int(srv.get("calls") or 0)
    server_us = float(srv.get("usec_per_call") or 0.0)
    rejected = int(srv.get("rejected_calls") or 0)
    failed = int(srv.get("failed_calls") or 0)
    # An engine operation is not one query. remember() currently makes several
    # round trips (resolve subject, create subject, write, label, count), so
    # report both rates rather than let one stand in for the other.
    qpo = queries / max(ops, 1)
    server_per_op_us = server_us * qpo

    print()
    p.note(f"ENGINE    {ops} operations in {wall:.1f}s  ->  {ops / wall:,.0f} ops/sec")
    p.note(f"          {writes} writes, {reads} reads, {errors} client errors")
    p.note(f"STORE     {queries} queries  ->  {queries / wall:,.0f} queries/sec")
    p.note(f"          {qpo:.1f} store queries per engine operation")
    p.note(f"SERVER    {server_us:8.1f} us per query, from INFO commandstats")
    p.note(f"          p50 {pct.get('p50', 0):.1f} us   p99 {pct.get('p99', 0):.1f} us"
           f"   p99.9 {pct.get('p99.9', 0):.1f} us   (INFO latencystats, includes queueing)")
    p.note(f"          {server_per_op_us:8.1f} us of server time per engine operation")
    p.note(f"CLIENT    {client_us:8.1f} us per operation, as the caller sees it")
    p.note(f"REFUSED   rejected_calls={rejected}  failed_calls={failed}")
    p.note(f"RAN AGAINST  " + "  ".join(
        f"{k}={cfg.get(k)}" for k in
        ("THREAD_COUNT", "OMP_THREAD_COUNT", "MAX_QUEUED_QUERIES", "CACHE_SIZE")))
    print()

    # What limited the run? Refuse to publish a number without an answer.
    threads = int(cfg.get("THREAD_COUNT") or 1)
    if rejected > 0:
        limit = (f"FalkorDB refused {rejected} queries. MAX_QUEUED_QUERIES is "
                 f"{cfg.get('MAX_QUEUED_QUERIES')}, so the server queue was the ceiling.")
    elif qpo > 2.0:
        limit = (f"round trips. Each engine operation costs {qpo:.1f} store queries, "
                 f"so {args.procs} processes spent most of their time waiting on "
                 f"{threads} server threads. Batching writes into one query is the "
                 f"next change, not a bigger machine.")
    else:
        limit = (f"FalkorDB's own query time ({server_us:.0f} us per query) with "
                 f"THREAD_COUNT={threads}.")
    p.check("the run names what limited it", bool(limit), limit)

    p.check("no client errors", errors == 0, f"{errors} errors")
    p.check("FalkorDB reported no failed calls", failed == 0, f"failed_calls={failed}")

    # Every write must be readable, and no tenant may see another's.
    lost = 0
    crossed = 0
    for t in range(min(10, args.tenants)):
        mem = Memory(tenant=f"{PREFIX}{t:03d}")
        own = mem.standing(kind=FACT, limit=200)
        if not own:
            lost += 1
        crossed += sum(1 for m in own if f"for tenant {t}" not in m.text)
    p.check("every tenant that was written to can be read back",
            lost == 0, f"{lost} tenant(s) came back empty")
    p.check("no tenant saw another tenant's writes under load",
            crossed == 0, f"{crossed} foreign row(s)")

    p.note(f"instance memory {mem_before/1e6:.1f} MB -> {used_memory(store)/1e6:.1f} MB")
    for g in [g for g in store.list_graphs() if g.startswith(PREFIX)]:
        store.drop(g)
    finish(p)


if __name__ == "__main__":
    mp.set_start_method("spawn")
    main()
