"""Criterion: handoffs between agents.

A second agent continues a first agent's work from shared state alone. No
summary, no transcript, no message of any kind passes between them.
"""

from __future__ import annotations

import multiprocessing as mp

from auryn import EPISODIC, SEMANTIC, Memory

from ._check import Proof, finish

TENANT, TASK = "proof-p3", "case-1"
FINDINGS = [
    "reproduced: the first request after an idle period is not retried",
    "the access token lifetime is 15 minutes",
]


def _first_agent(tenant: str) -> dict:
    """Investigates, records findings, then hands the work over."""
    mem = Memory(tenant=tenant)
    mem.forget_everything()
    mem = Memory(tenant=tenant)
    s = mem.start_session(agent="first")
    mem.create_task(TASK, title="idle request failure", agent="first",
                    subjects=["session expiry"])
    for text in FINDINGS:
        mem.remember(SEMANTIC, text, agent="first", subject="session expiry", session=s)
    mem.remember(EPISODIC, "three reporters described the same failure",
                 agent="first", subject="session expiry", session=s)
    h = mem.handoff(TASK, from_agent="first", to_agent="second", note="cause recorded")
    mem.end_session(s)
    return {"handoff_id": h.id, "at": h.at, "from": h.from_agent, "to": h.to_agent}


def _second_agent(payload: tuple[str, str]) -> dict:
    """A separate process. It receives TWO STRINGS and nothing else."""
    tenant, task = payload
    mem = Memory(tenant=tenant)
    ctx = mem.pick_up(task, agent="second")
    if ctx is None:
        return {"found": False}
    return {
        "found": True,
        "owner": ctx.owner,
        "handed_from": ctx.handed_from,
        "state": ctx.state,
        "memories": [m.text for m in ctx.memories],
    }


def _orphan_check(tenant: str) -> dict:
    """A task handed to an agent that never runs must not be lost."""
    mem = Memory(tenant=tenant)
    mem.create_task("orphan", title="nobody picked this up", agent="first")
    mem.handoff("orphan", from_agent="first", to_agent="ghost")
    opens = {t["task"]: t["owner"] for t in mem.open_tasks()}
    return {"open_tasks": opens}


def main() -> None:
    p = Proof("p3  handoff", "one agent picks up another agent's work").start()

    with mp.Pool(1) as pool:
        handed = pool.apply(_first_agent, (TENANT,))
    p.note(f"process 1: the first agent investigated and handed over, then exited")

    p.check("the handoff records who passed it, who received it, and when",
            handed["from"] == "first" and handed["to"] == "second" and handed["at"] > 0,
            f"{handed['from']} -> {handed['to']} at {handed['at']}")

    with mp.Pool(1) as pool:
        got = pool.apply(_second_agent, ((TENANT, TASK),))
    p.note("process 2: a separate process, given only a tenant id and a task id")

    p.check("the receiving agent found the work", got["found"])
    p.check("it knows who handed it over",
            got.get("handed_from") == "first", f"handed_from={got.get('handed_from')!r}")
    p.check("ownership moved to the receiving agent",
            got.get("owner") == "second", f"owner={got.get('owner')!r}")

    recalled = got.get("memories", [])
    for text in FINDINGS:
        p.check(f"it can state a finding it was never told: {text[:44]}",
                any(text in m for m in recalled))
    p.check("it reached every memory the first agent recorded",
            len(recalled) >= len(FINDINGS) + 1,
            f"{len(recalled)} memories reachable")

    # The channel check. The payload handed to process 2 was two strings.
    payload = (TENANT, TASK)
    p.check("no message, summary or transcript passed between the agents",
            all(isinstance(x, str) for x in payload) and len(payload) == 2,
            f"process 2 received exactly {payload!r}")

    with mp.Pool(1) as pool:
        orphan = pool.apply(_orphan_check, (TENANT,))
    p.check("a task handed to an agent that never runs stays open with an owner",
            orphan["open_tasks"].get("orphan") == "ghost",
            f"open tasks: {orphan['open_tasks']}")

    finish(p)


if __name__ == "__main__":
    mp.set_start_method("spawn")
    main()
