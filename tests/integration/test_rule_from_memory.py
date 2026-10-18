"""A stored procedure must govern behaviour, not just sit in the prompt.

Procedural memory is one of the three kinds Track 02 names. It was stored and
carried into prompts, but nothing acted on it, so a reader probing it found
nothing behind it. The triager now reads its escalation threshold from memory.

These tests pin that the behaviour follows the memory, in both directions.
"""

from __future__ import annotations

from auryn import PROCEDURAL, SEMANTIC, Memory
from demo.agents import _apply_escalation_rule

TENANT = "test-rule-from-memory"


def _fresh() -> Memory:
    m = Memory(tenant=TENANT)
    m.forget_everything()
    m = Memory(tenant=TENANT, consolidate_after=3)
    for n in range(4):
        m.remember("Event", f"issue {n} reports the thing", agent="t", subject="thing")
    return m


def _actions(mem: Memory) -> set[str]:
    return {e.action for e in _apply_escalation_rule(mem)}


def test_a_low_threshold_escalates() -> None:
    m = _fresh()
    m.remember(PROCEDURAL, "escalate at two", agent="t",
               subject="policy", trigger="reports>=2")
    assert "escalated" in _actions(m)
    m.forget_everything()


def test_a_high_threshold_does_not_escalate() -> None:
    m = _fresh()
    m.remember(PROCEDURAL, "escalate at fifty", agent="t",
               subject="policy", trigger="reports>=50")
    acted = _actions(m)
    assert "below rule" in acted
    assert "escalated" not in acted
    m.forget_everything()


def test_no_rule_in_memory_means_no_escalation() -> None:
    m = _fresh()
    acted = _actions(m)
    assert "no rule" in acted
    assert "escalated" not in acted
    m.forget_everything()


def test_changing_only_the_memory_changes_the_outcome() -> None:
    """The threshold is not a constant in the code. Prove it."""
    m = _fresh()
    low = m.remember(PROCEDURAL, "escalate at two", agent="t",
                     subject="policy", trigger="reports>=2")
    assert "escalated" in _actions(m)

    m.remember(PROCEDURAL, "escalate at fifty", agent="t", subject="policy",
               trigger="reports>=50", supersedes=[low.id])
    assert "escalated" not in _actions(m)
    m.forget_everything()
