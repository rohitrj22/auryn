"""Criterion: persistent conversation history.

A memory written in one process must survive that process exiting, and come
back in a new one with no history passed in.
"""

from __future__ import annotations

import multiprocessing as mp
import sys

from auryn import EPISODIC, PROCEDURAL, SEMANTIC, Memory

from ._check import Proof, finish

TENANT = "proof-p1"
FACTS = [
    (SEMANTIC, "the reporter prefers email over phone", "contact"),
    (PROCEDURAL, "close as duplicate only after the cause is recorded", "policy"),
    (EPISODIC, "issue 441 reported on 3 October", "issue-441"),
]


def _writer(tenant: str) -> list[str]:
    """Runs in its own process, then that process exits completely."""
    mem = Memory(tenant=tenant)
    mem.forget_everything()
    mem = Memory(tenant=tenant)
    session = mem.start_session(agent="writer")
    ids = []
    for idx, (kind, text, subject) in enumerate(FACTS):
        ids.append(mem.remember(kind, text, agent="writer", subject=subject, session=session).id)
        mem.add_turn(session, role="user", text=text, idx=idx)
    mem.end_session(session)
    return ids


def _reader(tenant: str) -> dict:
    """A different process. It receives only a tenant id."""
    mem = Memory(tenant=tenant)
    return {
        "standing": [m.text for m in mem.standing()],
        "episodic": [m.text for m in mem.recall("issue 441 reported", kind=EPISODIC)],
        "sessions": len(mem.history()),
        "turns": [t.text for t in mem.history(session=mem.history()[0].id)] if mem.history() else [],
    }


def _virgin(tenant: str) -> dict:
    mem = Memory(tenant=tenant)
    mem.forget_everything()
    mem = Memory(tenant=tenant)
    return {"standing": mem.standing(), "recall": mem.recall("anything at all")}


def main() -> None:
    p = Proof("p1  persistence", "memory outlives the process that wrote it").start()

    with mp.Pool(1) as pool:
        written = pool.apply(_writer, (TENANT,))
    p.note(f"process 1 wrote {len(written)} memories, then exited")

    with mp.Pool(1) as pool:
        got = pool.apply(_reader, (TENANT,))
    p.note("process 2 started fresh, given only a tenant id")

    standing_texts = set(got["standing"])
    for kind, text, _ in FACTS:
        if kind == EPISODIC:
            continue
        p.check(f"recalled after restart: {text[:48]}", text in standing_texts)

    p.check("the episodic memory also survived",
            any(FACTS[2][1] in t for t in got["episodic"]),
            f"recalled: {got['episodic']}")
    p.check("the session survived the writing process",
            got["sessions"] >= 1, f"{got['sessions']} session(s) readable")
    p.check("the turns read back in sequence",
            len(got["turns"]) == len(FACTS),
            f"{len(got['turns'])} of {len(FACTS)} turns")

    with mp.Pool(1) as pool:
        empty = pool.apply(_virgin, ("proof-p1-virgin",))
    p.check("a brand-new tenant invents nothing",
            not empty["standing"] and not empty["recall"],
            "standing and recall both empty, with no error")

    finish(p)


if __name__ == "__main__":
    mp.set_start_method("spawn")
    main()
