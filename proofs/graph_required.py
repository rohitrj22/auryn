"""Hackathon rule 3: the graph has to do real work.

The rule says a visualisation drawn on top of ordinary storage does not
qualify, and that the test is whether the product still works once FalkorDB is
taken out.

So this proof is the only one designed to confirm a FAILURE. Run it with
FalkorDB stopped. Every operation must fail, and every error must name the
store. If anything still answers, a second store exists, and the entry would
be disqualified.

    docker compose stop falkordb
    uv run python -m proofs.graph_required
    docker compose start falkordb
"""

from __future__ import annotations

from auryn import EVENT, Memory, StoreUnavailable

from ._check import Proof, finish

TENANT = "proof-p0"


def _expect_unavailable(p: Proof, label: str, fn) -> None:
    try:
        result = fn()
    except StoreUnavailable as exc:
        named = "falkordb" in str(exc).lower()
        p.check(label, named,
                f"raised StoreUnavailable; names the store: {named}")
        return
    except Exception as exc:  # noqa: BLE001 - any other error is still a failure to answer
        p.check(label, False,
                f"failed, but with {type(exc).__name__} instead of StoreUnavailable: {exc}")
        return
    p.check(label, False,
            f"IT STILL ANSWERED: {result!r}. A second store exists, which rule 3 disqualifies.")


def main() -> None:
    p = Proof("the graph does real work",
              "rule 3: remove FalkorDB and the product must stop").start()
    p.note("this proof expects failure. Run it with FalkorDB stopped.")

    _expect_unavailable(p, "opening a tenant's memory fails",
                        lambda: Memory(tenant=TENANT))

    # Everything below needs a live store even to construct, so prove the
    # constructor is the gate and that nothing is cached behind it.
    try:
        mem = Memory(tenant=TENANT)
    except StoreUnavailable:
        p.check("no cached handle survives to answer reads", True,
                "the engine cannot even be constructed without FalkorDB")
        p.check("the engine has no second store to fall back to", True,
                "there is no file store, no in-process cache, no other database")
        finish(p)
        return

    _expect_unavailable(p, "writing a memory fails",
                        lambda: mem.remember(EVENT, "x", agent="p0", subject="s"))
    _expect_unavailable(p, "recalling a memory fails", lambda: mem.recall("x"))
    _expect_unavailable(p, "reading standing memory fails", lambda: mem.standing())
    _expect_unavailable(p, "listing history fails", lambda: mem.history())
    _expect_unavailable(p, "picking up a handed-off task fails",
                        lambda: mem.pick_up("any-task"))
    finish(p)


if __name__ == "__main__":
    main()
