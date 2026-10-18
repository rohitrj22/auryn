"""Criterion: separate memory per user or tenant.

Isolation is the graph boundary. A query names one graph and cannot reach
another, so a leak is impossible rather than merely forbidden.

Counts come from FalkorDB's own commands, never from a count we kept.
"""

from __future__ import annotations

import argparse
import time

from auryn import SEMANTIC, Memory, Store
from auryn.metrics import graph_memory_usage, used_memory

from ._check import Proof, finish

PREFIX = "proof-p4-t"
SECRET = "the passphrase for tenant {n} is never shared"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenants", type=int, default=1000)
    ap.add_argument("--probes", type=int, default=1000)
    args = ap.parse_args()

    p = Proof("p4  tenant isolation",
              "separate memory per user or tenant").start()

    store = Store()
    for name in [g for g in store.list_graphs() if g.startswith(PREFIX)]:
        store.drop(name)

    before_mem = used_memory(store)
    before_count = len(store.list_graphs())

    t0 = time.perf_counter()
    for n in range(args.tenants):
        mem = Memory(tenant=f"{PREFIX}{n:05d}")
        mem.remember(SEMANTIC, SECRET.format(n=n), agent="setup", subject=f"secret-{n}")
    build_s = time.perf_counter() - t0

    after_mem = used_memory(store)
    graphs = [g for g in store.list_graphs() if g.startswith(PREFIX)]

    p.note(f"created {args.tenants} tenant graphs in {build_s:.2f}s "
           f"({args.tenants / build_s:.0f}/sec)")

    p.check(f"FalkorDB's own GRAPH.LIST counts {args.tenants} tenant graphs",
            len(graphs) == args.tenants,
            f"GRAPH.LIST reports {len(graphs)}; this is not a count we kept")

    per_tenant_kb = (after_mem - before_mem) / max(args.tenants, 1) / 1024
    p.note(f"instance memory {before_mem/1e6:.1f} MB -> {after_mem/1e6:.1f} MB")
    p.note(f"cost per tenant: {per_tenant_kb:.0f} KB "
           f"(from the INFO memory delta; GRAPH.MEMORY USAGE rounds to whole MB)")

    breakdown = graph_memory_usage(store, graphs[0])
    p.note(f"GRAPH.MEMORY USAGE breakdown keys: {', '.join(list(breakdown)[:4])}…")

    # Cross-tenant probes. Every one must come back empty.
    leaks: list[str] = []
    probes = 0
    sample = min(10, args.tenants)
    for i in range(sample):
        reader = Memory(tenant=f"{PREFIX}{i:05d}")
        for j in range(0, args.tenants, max(1, args.tenants // (args.probes // sample))):
            if i == j:
                continue
            probes += 1
            for row in reader.recall(SECRET.format(n=j)):
                if f"tenant {j} " in row.text:
                    leaks.append(f"{i} read {j}")
            if probes >= args.probes:
                break
        if probes >= args.probes:
            break

    p.check(f"zero memories crossed a tenant boundary in {probes} probes",
            not leaks, f"{len(leaks)} leak(s)" + (f": {leaks[:3]}" if leaks else ""))

    own = Memory(tenant=f"{PREFIX}00000").recall(SECRET.format(n=0))
    p.check("a tenant still reads its own memory",
            any("tenant 0 " in m.text for m in own),
            f"own recall returned {len(own)} row(s)")

    fresh = Memory(tenant=f"{PREFIX}-brand-new")
    p.check("a new tenant works with no setup step performed in advance",
            fresh.standing() == [] and fresh.recall("anything") == [],
            "empty, and no error")

    victim = f"{PREFIX}00001"
    Memory(tenant=victim).forget_everything()
    survivor = Memory(tenant=f"{PREFIX}00002").recall(SECRET.format(n=2))
    p.check("removing one tenant leaves the others untouched",
            bool(survivor), f"neighbour still has {len(survivor)} memory")

    ghost = Memory(tenant=f"{PREFIX}-does-not-exist")
    p.check("naming a tenant that never existed returns nothing, without error",
            ghost.recall("anything") == [])

    for name in [g for g in store.list_graphs() if g.startswith(PREFIX)]:
        store.drop(name)
    reclaimed = used_memory(store)
    p.note(f"after cleanup: {reclaimed/1e6:.1f} MB "
           f"({'reclaimed' if reclaimed < after_mem * 0.5 else 'NOT reclaimed'})")

    finish(p)


if __name__ == "__main__":
    main()
