"""The Auryn Triage Desk.

Point it at a public GitHub repository and watch a crew of agents triage the
open issues. No credential is required for any of this.

    uv run python -m demo.run --repo rohitrj22/auryn-triage-demo
    uv run python -m demo.run --inbox demo/data/inbox.json
    uv run python -m demo.run --new "note list empties after the app sits unused"
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import multiprocessing as mp
import os
import pathlib
import time

from auryn import SEMANTIC, Memory

from . import agents, source
from .agents import Event

BAR = "─" * 74


def head(n: int, title: str) -> None:
    print(f"\n{BAR}\n  PHASE {n}  {title}\n{BAR}")


def show(events: list[Event | dict]) -> None:
    for e in events:
        d = e if isinstance(e, dict) else e.__dict__
        read = f"  (read {d['prior_read']} prior)" if d.get("prior_read") else ""
        issue = f" {d['issue']:>4}" if d.get("issue") else "     "
        print(f"  {d['agent']:<12}{issue}  {d['action']:<13} {d['detail'][:78]}{read}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="auryn-triage", description="Triage issues with a crew of agents")
    ap.add_argument("--repo", help="public GitHub repo, for example owner/name")
    ap.add_argument("--inbox", type=pathlib.Path, default=source.CACHE, help="local issue file")
    ap.add_argument("--tenant", default="auryn-triage-demo", help="one isolated graph per tenant")
    ap.add_argument("--agents", type=int, default=6, help="how many investigators")
    ap.add_argument("--new", help="file one extra issue and let the crew see it")
    ap.add_argument("--fresh", action="store_true", help="clear this tenant's memory first")
    ap.add_argument("--report", type=pathlib.Path, default=pathlib.Path("output/triage-report.html"))
    args = ap.parse_args()

    timeline: list[dict] = []
    started = time.perf_counter()

    issues = source.load(args.repo, path=args.inbox)
    print(f"\n  Auryn Triage Desk")
    print(f"  source   : {args.repo or args.inbox}")
    print(f"  tenant   : {args.tenant}   (its own isolated graph)")
    print(f"  provider : {os.environ.get('AURYN_PROVIDER') or ('gemini' if os.environ.get('GEMINI_API_KEY') else 'mock')}")
    print(f"  issues   : {len(issues)}")

    mem = Memory(tenant=args.tenant)
    if args.fresh:
        mem.forget_everything()
        mem = Memory(tenant=args.tenant)

    # ---------------------------------------------------------------- phase 0
    head(0, "the coordinator opens the week")
    ev = agents.open_week(args.tenant, issues)
    timeline += [e.__dict__ for e in ev]
    show(ev)

    # ---------------------------------------------------------------- phase 1
    head(1, f"{args.agents} investigators work in parallel, sharing one memory")
    rows = {str(i.number): dataclasses.asdict(i) for i in issues}
    work = [(args.tenant, f"inv-{n}", rows) for n in range(1, args.agents + 1)]
    with mp.Pool(args.agents) as pool:
        results = pool.map(agents.investigate, work)
    flat = [e for batch in results for e in batch]
    flat.sort(key=lambda e: (e["action"] != "investigated", e["issue"]))
    timeline += flat
    show(flat)

    worked = [e for e in flat if e["action"] == "investigated"]
    skipped = [e for e in flat if e["action"] == "skipped"]
    seen = [e["issue"] for e in flat]
    print(f"\n  claimed {len(seen)} of {len(issues)} issues   "
          f"investigated {len(worked)}   recognised from memory {len(skipped)}   "
          f"duplicated work {len(seen) - len(set(seen))}")

    # ---------------------------------------------------------------- phase 2
    head(2, "the engine concluded something nobody told it")
    derived = [m for m in mem.standing(kind=SEMANTIC) if m.derived]
    for fact in derived:
        prov = mem.explain(fact.id)
        print(f"  derived  {fact.text}")
        for e in (prov.derived_from if prov else []):
            print(f"      evidence  {e.text[:70]}")
    if not derived:
        print("  (no subject reached the threshold)")
    timeline += [{"agent": "engine", "action": "derived", "issue": "",
                  "detail": f.text, "prior_read": 0,
                  "extra": {"evidence": [e.text for e in (mem.explain(f.id).derived_from if mem.explain(f.id) else [])]}}
                 for f in derived]

    # ---------------------------------------------------------------- phase 3
    head(3, "the triager takes ownership, then hands the week over")
    ev = agents.triage(args.tenant)
    timeline += [e.__dict__ for e in ev]
    show(ev)

    # ---------------------------------------------------------------- phase 4
    head(4, "the assignee picks up, in a separate process, with two strings")
    with mp.Pool(1) as pool:
        ev = pool.apply(_assign_in_child, (args.tenant,))
    timeline += ev
    show(ev)

    # ---------------------------------------------------------------- phase 5
    if args.new:
        head(5, "a new issue arrives, in a fresh process, with no history passed in")
        fresh = source.Issue(number=999, title=args.new, body=args.new,
                             author="newcomer", created_at="")
        with mp.Pool(1) as pool:
            ev = pool.apply(_recall_in_child, (args.tenant, dataclasses.asdict(fresh)))
        timeline += ev
        show(ev)

    # ---------------------------------------------------------------- phase 6
    head(6, "the auditor answers 'why do you believe that?'")
    ev = agents.audit(args.tenant)
    timeline += [e.__dict__ for e in ev]
    show(ev)
    for e in ev:
        for line in e.extra.get("evidence", [])[:5]:
            print(f"      from  {line[:70]}")
        for line in e.extra.get("replaced", [])[:3]:
            print(f"      was   {line[:70]}")

    # ---------------------------------------------------------------- phase 7
    head(7, "another repository's memory is unreachable from here")
    other = Memory(tenant="some-other-repo")
    other.forget_everything()
    other = Memory(tenant="some-other-repo")
    other.remember(SEMANTIC, "root cause unrelated-thing: belongs to another repo",
                   agent="coordinator", subject="unrelated")
    here = [m.text for m in mem.recall("unrelated-thing")]
    there = [m.text for m in other.recall("session-expiry")]
    print(f"  this tenant recalls the other repo's cause : {here}   <- must be empty")
    print(f"  the other tenant recalls this repo's cause : {there}   <- must be empty")

    # ---------------------------------------------------------------- report
    elapsed = time.perf_counter() - started
    stats = mem.stats()
    payload = {
        "repo": args.repo or str(args.inbox),
        "tenant": args.tenant,
        "issues": [dataclasses.asdict(i) for i in issues],
        "timeline": timeline,
        "elapsed_s": round(elapsed, 2),
        "graph_count": stats.graph_count,
        "used_memory_mb": round(stats.used_memory_bytes / 1e6, 2),
        "percentiles": stats.latency_percentiles.get("graph.QUERY", {}),
        "config": {k: stats.config.get(k) for k in
                   ("THREAD_COUNT", "OMP_THREAD_COUNT", "MAX_QUEUED_QUERIES", "CACHE_SIZE")},
        "counts": {"claimed": len(seen), "investigated": len(worked),
                   "recognised": len(skipped), "duplicated": len(seen) - len(set(seen))},
    }
    pathlib.Path("output").mkdir(exist_ok=True)
    pathlib.Path("output/triage-run.json").write_text(json.dumps(payload, indent=2) + "\n")

    from .report import write_report
    write_report(payload, args.report)
    print(f"\n{BAR}")
    print(f"  run took {elapsed:.1f}s   report written to {args.report}")
    print(f"{BAR}\n")


def _assign_in_child(tenant: str) -> list[dict]:
    return [e.__dict__ for e in agents.assign(tenant)]


def _recall_in_child(tenant: str, issue_row: dict) -> list[dict]:
    return [e.__dict__ for e in agents.recall_known(tenant, source.Issue(**issue_row))]


if __name__ == "__main__":
    mp.set_start_method("spawn")
    main()
