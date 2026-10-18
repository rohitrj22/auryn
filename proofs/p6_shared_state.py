"""Criterion: shared state between agents.

Many agents work ONE job at the same time. They read each other's findings
while the others are still working, and no two agents repeat the same work.
"""

from __future__ import annotations

import argparse
import multiprocessing as mp

from auryn import SEMANTIC, Memory

from ._check import Proof, finish

TENANT, JOB = "proof-p6", "shared-job"


def _worker(args: tuple[str, int, int]) -> dict:
    """A swarm member. Joins, claims parts, reads shared state, contributes."""
    tenant, n, parts = args
    mem = Memory(tenant=tenant)
    name = f"agent{n}"
    mem.join(JOB, agent=name)
    done, saw = [], []
    while True:
        free = mem.unclaimed_parts(JOB)
        if not free:
            break
        got = next((p for p in free if mem.claim(p["task"], agent=name)), None)
        if got is None:
            continue
        prior = mem.standing(kind=SEMANTIC)   # what the others already found
        saw.append(len(prior))
        mem.remember(SEMANTIC, f"finding for {got['title']} by {name}",
                     agent=name, subject=str(got["title"]))
        mem.set_task_state(got["task"], "done")
        done.append(got["task"])
    mem.leave(JOB, agent=name)
    return {"agent": name, "done": done, "saw": saw}


def _claim_race(args: tuple[str, str, int]) -> bool:
    tenant, task, n = args
    return Memory(tenant=tenant).claim(task, agent=f"racer{n}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agents", type=int, default=8)
    ap.add_argument("--parts", type=int, default=10)
    ap.add_argument("--race-rounds", type=int, default=25)
    ap.add_argument("--racers", type=int, default=16)
    args = ap.parse_args()

    p = Proof("p6  shared state", "many agents share state on one job").start()

    mem = Memory(tenant=TENANT); mem.forget_everything()
    mem = Memory(tenant=TENANT)
    mem.create_task(JOB, title="one job, many agents", agent="coordinator")
    topics = [f"topic-{i:02d}" for i in range(args.parts)]
    for i, t in enumerate(topics):
        mem.add_part(JOB, f"{JOB}-p{i}", title=t, subjects=[t])

    with mp.Pool(args.agents) as pool:
        results = pool.map(_worker, [(TENANT, n, args.parts) for n in range(1, args.agents + 1)])

    all_done = [t for r in results for t in r["done"]]
    active = [r["agent"] for r in results if r["done"]]
    p.note(f"{args.agents} agents worked one job of {args.parts} parts; "
           f"{len(active)} of them got work")

    p.check(f"all {args.parts} parts completed",
            len(set(all_done)) == args.parts,
            f"{len(set(all_done))} distinct parts done")
    p.check("zero duplicated work",
            len(all_done) == len(set(all_done)),
            f"{len(all_done)} claims, {len(set(all_done))} distinct")
    p.check("more than one agent contributed",
            len(active) > 1, f"agents that did work: {sorted(active)}")

    findings = mem.standing(kind=SEMANTIC)
    p.check("every finding is readable by every agent",
            len(findings) == args.parts,
            f"{len(findings)} findings in shared memory, written by "
            f"{len({f.agent for f in findings})} different agents")

    # Did agents read each other MID-FLIGHT, not only at the end?
    mid = [s for r in results for s in r["saw"]]
    grew = sorted(mid) != mid or (max(mid) > 0 and min(mid) < max(mid))
    p.check("agents read findings while others were still working",
            max(mid) > 0 and min(mid) < max(mid),
            f"prior findings visible per claim ranged {min(mid)}..{max(mid)}")

    # Atomic claim under real process contention.
    winners_per_round = []
    for r in range(args.race_rounds):
        task = f"{JOB}-race-{r}"
        mem.create_task(task, title=f"race {r}", agent="coordinator")
        with mp.Pool(args.racers) as pool:
            got = pool.map(_claim_race, [(TENANT, task, n) for n in range(args.racers)])
        winners_per_round.append(sum(1 for g in got if g))
    p.check(f"exactly one winner per round, {args.racers} processes x {args.race_rounds} rounds",
            all(w == 1 for w in winners_per_round),
            f"winners per round: {sorted(set(winners_per_round))} "
            f"({args.racers * args.race_rounds} attempts, "
            f"{sum(winners_per_round)} winners)")

    p.check("the in-flight view is empty once every agent has left",
            mem.in_flight() == [], f"in flight: {mem.in_flight()}")

    status = {r["state"]: r["n"] for r in mem.parts_status(JOB)}
    p.check("progress across every part is readable in one request",
            status.get("done") == args.parts, f"parts by state: {status}")

    finish(p)


if __name__ == "__main__":
    mp.set_start_method("spawn")
    main()
