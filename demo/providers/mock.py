"""A deterministic stand-in for a language model.

It exists so a judge with no credentials runs every proof, and so the proofs
give the same result every time.

Be clear about what this is: the diagnosis below is **scripted keyword
scoring, not reasoning**. With GEMINI_API_KEY set, the model does the
diagnosis for real. The README says so plainly.

The engine cannot tell the difference, because both return the same shape.
"""

from __future__ import annotations

import re
from typing import Any

from auryn.models import EVENT, PROCEDURE, FACT

from . import MemoryOp, Reply

# Weighted signals per cause. Highest score wins; ties fall through to unknown.
# Deliberately NOT a single giveaway word: the five session-expiry reports
# share a situation, not a phrase.
CAUSES: tuple[tuple[str, str, tuple[tuple[str, int], ...]], ...] = (
    (
        "session-expiry",
        "the access token expires while the app is idle, and the first request after that is not retried",
        (
            ("idle", 3), ("overnight", 3), ("sleep", 3), ("untouched", 3), ("unused", 3),
            ("token", 3), ("401", 3), ("token_expired", 4), ("ttl", 3),
            ("morning", 2), ("relaunch", 2), ("restart", 2), ("force quit", 2),
            ("refresh", 2), ("kill -9", 2), ("haven't touched", 3), ("over lunch", 3),
        ),
    ),
    (
        "pdf-export",
        "the print-to-PDF path captures the page before the renderer has painted",
        (("pdf", 4), ("export", 2), ("print", 3), ("page count", 3), ("html export", 3)),
    ),
    (
        "search-performance",
        "the search index is rebuilt per keystroke instead of queried incrementally",
        (("latency", 4), ("keystroke", 4), ("index", 2), ("rebuilt", 3),
         ("cpu", 3), ("slow", 2), ("measurements", 2), ("vault size", 3)),
    ),
    (
        "docs-copy",
        "a wording error in the committed documentation",
        (("docs/", 4), ("typo", 4), ("agreement", 3), ("subject-verb", 4), ("reads:", 2)),
    ),
    (
        "theme-persistence",
        "the theme is applied before stored settings are read on startup",
        (("theme", 4), ("appearance", 3), ("settings.json", 4), ("dark mode", 3), ("light theme", 3)),
    ),
    (
        "platform-path",
        "a platform-specific path or file-locking difference",
        (("windows", 3), ("file-locking", 4), ("c:\\", 3), ("%appdata%", 2), ("23h2", 2)),
    ),
)

_SUBJECT_WORDS = re.compile(r"[a-z0-9]+")


def diagnose(text: str) -> tuple[str, str, int]:
    """Return (cause, explanation, score). Scripted scoring, not reasoning."""
    low = text.lower()
    best = ("unknown", "no recognised signals in the report", 0)
    for cause, explanation, signals in CAUSES:
        score = sum(weight for token, weight in signals if token in low)
        if score > best[2]:
            best = (cause, explanation, score)
    return best


class MockProvider:
    name = "mock"

    def respond(self, messages: list[dict[str, str]], *, recalled: list[Any] = ()) -> Reply:
        last = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        cause, explanation, score = diagnose(last)

        ref = next((m["content"] for m in messages if m.get("role") == "ref"), "this report")

        # Does a cause already in memory explain this report?
        known = next((m for m in (recalled or []) if cause and cause in (m.text or "")), None)

        if known is not None:
            # A duplicate. Record that the report arrived, and nothing more.
            return Reply(
                text=f"{ref} matches a cause already in memory: {cause}.",
                memory_ops=[
                    MemoryOp(kind=EVENT, text=f"{ref} reported, same cause as known {cause}",
                             subjects=(cause,)),
                ],
            )

        # A new cause. Record the lasting fact AND that the report arrived.
        return Reply(
            text=f"Reproduced {ref}. Cause: {cause} — {explanation}.",
            memory_ops=[
                MemoryOp(kind=FACT, text=f"root cause {cause}: {explanation}",
                         subjects=(cause,)),
                MemoryOp(kind=EVENT, text=f"{ref} reported and reproduced",
                         subjects=(cause,)),
            ],
        )
