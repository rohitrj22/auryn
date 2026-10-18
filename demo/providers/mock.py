"""A deterministic stand-in for a language model.

It exists so a judge with no credentials can run every proof. The same input
always gives the same output, and no network call is made.

It produces the same shape a real model produces: a reply, plus the memory
operations it decided on. The engine cannot tell the difference.
"""

from __future__ import annotations

import re
from typing import Any

from auryn.models import EPISODIC, PROCEDURAL, SEMANTIC
from . import MemoryOp, ProviderFailure, Reply

# Scripted stand-ins for a model's judgement. Pattern -> (kind, subject hint).
_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(prefer|rather|instead of|always|never)\b", re.I), SEMANTIC),
    (re.compile(r"\b(must|needs?|requires?|policy|above|threshold)\b", re.I), PROCEDURAL),
)

_SUBJECT = re.compile(r"\b([a-z]+\s*#?\d{2,})\b", re.I)


def _kind_for(text: str) -> str:
    for pattern, kind in _RULES:
        if pattern.search(text):
            return kind
    return EPISODIC


def _subjects_for(text: str) -> tuple[str, ...]:
    found = [m.group(1).strip() for m in _SUBJECT.finditer(text)]
    return tuple(dict.fromkeys(found)) if found else ()


class MockProvider:
    name = "mock"

    def respond(self, messages: list[dict[str, str]], *, recalled: list[Any] = ()) -> Reply:
        last = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")

        if recalled:
            known = recalled[0]
            opening = f"I remember: {known.text}."
        else:
            opening = "I have no memory of this yet."

        text = f"{opening} You said: {last}" if last else opening

        ops: list[MemoryOp] = []
        if last:
            ops.append(
                MemoryOp(kind=_kind_for(last), text=last.strip(), subjects=_subjects_for(last))
            )
        return Reply(text=text, memory_ops=ops)
