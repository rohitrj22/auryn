"""The triage crew. Five roles, all of them thin.

Every role reaches the shared memory through Auryn and nothing else. No agent
sends a message to another agent. The graph is the only channel.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from auryn import EPISODIC, PROCEDURAL, SEMANTIC, Memory

from .providers import get_provider
from .source import Issue

TASK = "triage"


@dataclass
class Event:
    """One line for the timeline and the report page."""

    agent: str
    action: str
    issue: str = ""
    detail: str = ""
    prior_read: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


def _mem(tenant: str) -> Memory:
    return Memory(tenant=tenant, consolidate_after=3)


# --------------------------------------------------------------------- setup


def open_batch(tenant: str, issues: list[Issue], *, task: str = TASK) -> list[Event]:
    """Open one triage batch and make each issue a claimable part."""
    mem = _mem(tenant)
    mem.create_task(task, title="open issues to triage", agent="coordinator")
    mem.remember(
        PROCEDURAL,
        "close an issue as a duplicate only after the shared cause is recorded",
        agent="coordinator", subject="triage policy",
    )
    mem.remember(
        SEMANTIC,
        "the sync layer is owned by the platform team",
        agent="coordinator", subject="ownership",
    )
    for issue in issues:
        mem.add_part(task, f"{task}-{issue.number}", title=issue.ref, subjects=[issue.ref])
    return [Event(agent="coordinator", action="opened",
                  detail=f"{len(issues)} issues made claimable",
                  extra={"issues": [i.number for i in issues]})]


# --------------------------------------------------------- the swarm member


def investigate(args: tuple[str, str, dict[int, dict]]) -> list[dict]:
    """One investigator. Claims parts, reads shared memory, works or skips.

    Runs in its own process. It receives a tenant, its own name, and the issue
    text. It receives nothing from any other agent.
    """
    tenant, name, issue_rows = args
    issues = {int(k): Issue(**v) for k, v in issue_rows.items()}
    mem = _mem(tenant)
    provider = get_provider()
    mem.join(TASK, agent=name)
    events: list[Event] = []

    while True:
        parts = mem.unclaimed_parts(TASK)
        if not parts:
            break
        claimed = next((p for p in parts if mem.claim(p["task"], agent=name)), None)
        if claimed is None:
            continue  # another agent took them all; re-read and see what is left

        number = int(str(claimed["task"]).rsplit("-", 1)[-1])
        issue = issues[number]

        # READ BEFORE WORKING. This is where one agent benefits from another.
        context = mem.standing() + mem.recall(issue.title)
        context = list({m.id: m for m in context}.values())

        reply = provider.respond(
            [{"role": "ref", "content": issue.ref}, {"role": "user", "content": issue.text}],
            recalled=context,
        )

        cause_ops = [op for op in reply.memory_ops if op.kind == SEMANTIC]

        if cause_ops:
            # A cause nobody has recorded yet. Claim the CAUSE, not just the
            # issue, so two agents never investigate the same thing at once.
            # Claiming the issue alone is not enough: several agents can
            # diagnose the same cause in the same instant.
            cause = cause_ops[0].subjects[0] if cause_ops[0].subjects else issue.ref
            lane = f"cause:{cause}"
            mem.create_task(lane, title=cause, agent=name)
            if mem.claim(lane, agent=name):
                action = "investigated"
            else:
                # Another agent owns this investigation. Record the report only.
                action = "deferred"
                reply.memory_ops[:] = [op for op in reply.memory_ops if op.kind != SEMANTIC]
                reply = type(reply)(
                    text=f"another agent is recording {cause}; logged {issue.ref} "
                         f"against it",
                    memory_ops=[op for op in reply.memory_ops if op.kind != SEMANTIC],
                )
        else:
            action = "skipped"

        for op in reply.memory_ops:
            mem.remember(op.kind, op.text, agent=name,
                         subject=(op.subjects[0] if op.subjects else issue.ref),
                         subjects=tuple(op.subjects[1:]) + (issue.ref,),
                         trigger=op.trigger)

        events.append(Event(
            agent=name,
            action=action,
            issue=issue.ref,
            detail=reply.text,
            prior_read=len(context),
        ))
        mem.set_task_state(claimed["task"], "done")

    mem.leave(TASK, agent=name)
    return [e.__dict__ for e in events]


# ------------------------------------------------------------------- triager


def triage(tenant: str, *, task: str = TASK) -> list[Event]:
    """Read every finding, correct a wrong one, then hand the batch over."""
    mem = _mem(tenant)
    events: list[Event] = []

    causes = mem.standing(kind=SEMANTIC)
    events.append(Event(agent="triager", action="read",
                        detail=f"read {len(causes)} lasting facts the swarm recorded",
                        prior_read=len(causes)))

    # Correct the platform-path diagnosis: the same expiry, reached sooner.
    wrong = [c for c in causes if c.text.startswith("root cause platform-path")]
    if wrong:
        mem.remember(
            SEMANTIC,
            "root cause session-expiry: the Windows reports share the token expiry; "
            "that machine idles sooner, so it is not a platform-path fault",
            agent="triager", subject="session-expiry",
            supersedes=[c.id for c in wrong],
        )
        events.append(Event(agent="triager", action="corrected",
                            detail="superseded the platform-path diagnosis",
                            extra={"superseded": [c.id for c in wrong]}))

    mem.handoff(task, from_agent="triager", to_agent="assignee",
                note="root cause recorded; ready to fix")
    events.append(Event(agent="triager", action="handoff", detail="triager -> assignee"))
    return events


# ------------------------------------------------------------------ assignee


def assign(tenant: str, *, task: str = TASK) -> list[Event]:
    """Receive the batch with two strings and nothing else."""
    mem = _mem(tenant)
    ctx = mem.pick_up(task, agent="assignee")
    if ctx is None:
        return [Event(agent="assignee", action="nothing", detail="no such task")]

    events = [Event(
        agent="assignee", action="picked up",
        detail=f"handed from {ctx.handed_from!r}; can state {len(ctx.memories)} memories "
               f"it was never told",
        prior_read=len(ctx.memories),
        extra={"memories": [m.text for m in ctx.memories]},
    )]
    mem.remember(EPISODIC, "fix shipped in PR #88: refresh the token before a scheduled fetch",
                 agent="assignee", subject="session-expiry")
    mem.handoff(task, from_agent="assignee", to_agent="reviewer", note="PR #88 open")
    events.append(Event(agent="assignee", action="handoff", detail="assignee -> reviewer"))
    return events


# ----------------------------------------------------------------- historian


def recall_known(tenant: str, issue: Issue) -> list[Event]:
    """Runs in a fresh process. Nothing is passed in but a tenant and a text."""
    mem = _mem(tenant)
    context = mem.standing() + mem.recall(issue.title)
    context = list({m.id: m for m in context}.values())
    hit = next((m for m in context if m.kind == SEMANTIC and "session-expiry" in m.text), None)
    return [Event(
        agent="historian", action="recognised" if hit else "unknown",
        issue=issue.ref,
        detail=(f"recognised from memory: {hit.text[:88]}" if hit else "no memory of this"),
        prior_read=len(context),
    )]


# -------------------------------------------------------------------- auditor


def audit(tenant: str) -> list[Event]:
    """Answers 'why do you believe that?' from the graph alone."""
    mem = _mem(tenant)
    derived = [m for m in mem.standing(kind=SEMANTIC) if m.derived]
    events: list[Event] = []
    for fact in derived:
        prov = mem.explain(fact.id)
        if prov is None:
            continue
        events.append(Event(
            agent="auditor", action="explained",
            detail=f"{prov.text}  <- counted {len(prov.derived_from)} reports",
            extra={"evidence": [e.text for e in prov.derived_from]},
        ))
    for fact in mem.standing(kind=SEMANTIC):
        prov = mem.explain(fact.id)
        if prov and prov.supersedes:
            events.append(Event(
                agent="auditor", action="belief changed",
                detail=f"now: {prov.text[:70]}",
                extra={"replaced": [o.text for o in prov.supersedes]},
            ))
    return events
