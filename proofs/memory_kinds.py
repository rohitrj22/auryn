"""Criterion: episodic, semantic and procedural memory.

Three kinds, stored and recalled separately. Plus the two behaviours that make
them useful: a corrected belief is kept, and repeated events become a fact.
"""

from __future__ import annotations

from auryn import EVENT, PROCEDURE, FACT, Memory

from ._check import Proof, finish

TENANT = "proof-p2"


def main() -> None:
    p = Proof("memory kinds", "episodic, semantic and procedural memory").start()

    mem = Memory(tenant=TENANT); mem.forget_everything()
    mem = Memory(tenant=TENANT, consolidate_after=3)
    s = mem.start_session(agent="p2")

    mem.remember(EVENT, "issue 501 reported a crash on launch",
                 agent="p2", subject="issue-501", session=s)
    mem.remember(FACT, "the sync layer is owned by the platform team",
                 agent="p2", subject="ownership", session=s)
    mem.remember(PROCEDURE, "a release above risk level 3 needs a second reviewer",
                 agent="p2", subject="release policy", session=s, trigger="risk>3")

    query = "issue 501 crash sync platform release reviewer"
    for kind, expect in ((EVENT, "issue 501"), (FACT, "platform team"),
                         (PROCEDURE, "second reviewer")):
        got = mem.recall(query, kind=kind)
        kinds = {m.kind for m in got}
        p.check(f"{kind} requested alone returns only {kind}",
                kinds == {kind} and any(expect in m.text for m in got),
                f"{len(got)} row(s), kinds={sorted(kinds)}")

    allk = mem.recall(query)
    p.check("requesting no kind returns more than one kind",
            len({m.kind for m in allk}) > 1,
            f"kinds={sorted({m.kind for m in allk})}")

    proc = mem.recall(query, kind=PROCEDURE)
    p.check("a procedure carries the condition it applies under",
            bool(proc) and proc[0].trigger == "risk>3",
            f"trigger={proc[0].trigger if proc else None!r}")

    # Two different facts about one subject must coexist.
    mem.remember(FACT, "allergic to peanuts", agent="p2", subject="allergies")
    mem.remember(FACT, "allergic to shellfish", agent="p2", subject="allergies")
    both = [m.text for m in mem.standing(kind=FACT)]
    p.check("two different facts about one subject coexist",
            "allergic to peanuts" in both and "allergic to shellfish" in both,
            "neither buried the other")

    # A corrected belief is kept and flagged.
    old = mem.remember(FACT, "the cause is a platform path difference",
                       agent="p2", subject="cause-x")
    new = mem.remember(FACT, "the cause is a token expiry",
                       agent="p2", subject="cause-x", supersedes=old.id)
    current = [m.text for m in mem.standing(kind=FACT)]
    history = {m.text: m.superseded for m in
               mem.recall("cause platform token expiry", kind=FACT,
                          include_superseded=True)}
    p.check("the corrected belief replaces the old one in current answers",
            "the cause is a token expiry" in current
            and "the cause is a platform path difference" not in current)
    p.check("the old belief is kept and flagged, never deleted",
            history.get("the cause is a platform path difference") is True,
            f"superseded flags: {history}")
    prov = mem.explain(new.id)
    p.check("the new belief records what it replaced",
            bool(prov and prov.supersedes),
            f"supersedes: {[x.text for x in (prov.supersedes if prov else [])]}")

    # Repeated events on one subject become a fact, with its evidence.
    for n in (601, 602, 603):
        mem.remember(EVENT, f"issue {n} reported the same timeout",
                     agent="p2", subject="timeout", session=s)
    derived = [m for m in mem.standing(kind=FACT) if m.derived]
    p.check("three events on one subject derived a fact",
            len(derived) >= 1, f"derived: {[m.text for m in derived]}")
    if derived:
        prov = mem.explain(derived[0].id)
        p.check("the derived fact links every event it counted",
                bool(prov) and len(prov.derived_from) >= 3,
                f"{len(prov.derived_from) if prov else 0} events linked")
        p.check("no language model took part in deriving it",
                all(e.agent != "gemini" for e in (prov.derived_from if prov else []))
                and derived[0].agent == "auryn",
                f"written by {derived[0].agent!r} (the engine), by counting")

    finish(p)


if __name__ == "__main__":
    main()
