"""Auryn's public surface.

Six operations. No business vocabulary. One graph per tenant, so isolation is
the graph boundary rather than a filter in a query.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

from . import consolidate
from . import queries as q
from . import schema
from .models import (
    EPISODIC,
    PROCEDURAL,
    SEMANTIC,
    Handoff,
    MemoryRecord,
    Provenance,
    Session,
    TaskContext,
    Turn,
    clamp_text,
    validate_kind,
    validate_tenant,
)
from .store import Store


def _now() -> int:
    return int(time.time() * 1000)


def _rid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _record(row: dict[str, Any]) -> MemoryRecord:
    kinds = row.get("kinds") or []
    kind = next((k for k in kinds if k != "Memory"), "Memory")
    return MemoryRecord(
        id=row["id"],
        kind=kind,
        text=row.get("text") or "",
        at=int(row.get("at") or 0),
        agent=row.get("agent") or "",
        session_id=row.get("session_id"),
        subject_key=row.get("subject_key"),
        derived=bool(row.get("derived")),
        superseded=bool(row.get("superseded")),
        truncated=bool(row.get("truncated")),
        trigger=row.get("trigger"),
        hops=row.get("hops"),
        score=row.get("score"),
    )


def _rows(res) -> list[dict[str, Any]]:
    headers = [h[1] if isinstance(h, (list, tuple)) else h for h in res.header]
    return [dict(zip(headers, r)) for r in (res.result_set or [])]


class Memory:
    """A tenant's whole memory. Opening one is cheap; the connection is shared."""

    def __init__(
        self,
        tenant: str,
        *,
        url: str | None = None,
        store: Store | None = None,
        consolidate_after: int = 3,
        recall_cap: int = 20,
    ) -> None:
        self.tenant = validate_tenant(tenant)
        self.store = store or Store(url=url)
        self.consolidate_after = int(consolidate_after)
        self.recall_cap = int(recall_cap)
        schema.ensure(self.store, self.tenant)

    # ---------------------------------------------------------------- sessions

    def start_session(self, *, agent: str) -> Session:
        sid = _rid("s")
        at = _now()
        self.store.query(self.tenant, q.START_SESSION, {"id": sid, "at": at, "agent": agent})
        return Session(id=sid, started_at=at, agent=agent)

    def end_session(self, session: str | Session) -> None:
        sid = session.id if isinstance(session, Session) else session
        self.store.query(self.tenant, q.END_SESSION, {"id": sid, "at": _now()})

    def add_turn(self, session: str | Session, *, role: str, text: str, idx: int) -> Turn:
        sid = session.id if isinstance(session, Session) else session
        body, _ = clamp_text(text)
        tid = _rid("t")
        at = _now()
        self.store.query(
            self.tenant,
            q.ADD_TURN,
            {"session": sid, "id": tid, "role": role, "text": body, "idx": idx, "at": at},
        )
        return Turn(id=tid, role=role, text=body, idx=idx, at=at)

    def history(self, *, session: str | Session | None = None, limit: int = 20):
        """A session's turns in sequence, or the tenant's sessions, newest first."""
        if session is not None:
            sid = session.id if isinstance(session, Session) else session
            rows = _rows(self.store.query(self.tenant, q.SESSION_TURNS, {"session": sid}))
            return [Turn(id=r["id"], role=r["role"], text=r["text"], idx=int(r["idx"]), at=int(r["at"])) for r in rows]
        rows = _rows(self.store.query(self.tenant, q.LIST_SESSIONS, {"limit": int(limit)}))
        return [
            Session(
                id=r["id"],
                started_at=int(r["started_at"] or 0),
                ended_at=int(r["ended_at"]) if r.get("ended_at") is not None else None,
                agent=r.get("agent"),
            )
            for r in rows
        ]

    # ---------------------------------------------------------------- write

    def remember(
        self,
        kind: str,
        text: str,
        *,
        agent: str,
        subject: str | None = None,
        subjects: tuple[str, ...] | list[str] = (),
        session: str | Session | None = None,
        id: str | None = None,
        trigger: str | None = None,
        supersedes: str | tuple[str, ...] | list[str] = (),
    ) -> MemoryRecord:
        """Write one memory. A repeat write of the same id updates it.

        Pass `supersedes` to mark earlier memories as out of date. The engine
        never infers this. Two facts about one subject coexist by default, which
        is both correct and safe when several agents write at once.
        """
        validate_kind(kind)
        body, truncated = clamp_text(text)
        names = [n for n in ([subject] if subject else []) + list(subjects) if n]
        if not names:
            names = ["general"]

        keys: list[str] = []
        for name in names:
            key, related = schema.resolve_subject(self.store, self.tenant, name)
            self.store.query(self.tenant, q.CREATE_SUBJECT, {"key": key, "name": name})
            if related and related != key:
                # Ambiguity becomes an edge, never a wrong merge.
                self.store.query(self.tenant, q.LINK_SUBJECTS, {"a": key, "b": related})
            keys.append(key)

        mid = id or _rid("m")
        sid = session.id if isinstance(session, Session) else session
        at = _now()
        self.store.query(
            self.tenant,
            q.WRITE_MEMORY,
            {
                "id": mid,
                "text": body,
                "at": at,
                "subject_key": keys[0],
                "agent": agent,
                "session_id": sid,
                "truncated": truncated,
                "derived": False,
                "trigger": trigger,
                "subjects": keys,
            },
        )
        self.store.query(self.tenant, q.ADD_KIND_LABEL.format(label=kind), {"id": mid})

        old_ids = [supersedes] if isinstance(supersedes, str) else list(supersedes)
        if old_ids:
            self.store.query(self.tenant, q.SUPERSEDE, {"old_ids": old_ids, "new_id": mid})
        if kind == EPISODIC:
            consolidate.maybe_derive(
                self.store, self.tenant, keys[0],
                threshold=self.consolidate_after, at=at, session_id=sid,
            )

        return MemoryRecord(
            id=mid, kind=kind, text=body, at=at, agent=agent,
            session_id=sid, subject_key=keys[0], truncated=truncated, trigger=trigger,
        )

    # ---------------------------------------------------------------- read

    def recall(
        self,
        query: str,
        *,
        kind: str | None = None,
        limit: int | None = None,
        include_superseded: bool = False,
        subject: str | None = None,
    ) -> list[MemoryRecord]:
        """Memories ranked by connection closeness, then recency. One round trip.

        Never filters by session or by agent. That omission is what makes recall
        work across sessions and across agents.
        """
        if kind is not None:
            validate_kind(kind)
        cap = int(limit or self.recall_cap)

        if subject is not None:
            key, _ = schema.resolve_subject(self.store, self.tenant, subject)
            res = self.store.query(
                self.tenant, q.RECALL_BY_SUBJECT,
                {"subject": key, "kind": kind, "include_superseded": include_superseded, "cap": cap},
            )
            return [_record(r) for r in _rows(res)]

        terms = q.terms_or(query)
        if not terms:
            return []
        res = self.store.query(
            self.tenant, q.RECALL,
            {"terms": terms, "kind": kind, "include_superseded": include_superseded, "cap": cap},
        )
        return [_record(r) for r in _rows(res)]

    def standing(
        self,
        *,
        kind: str | None = None,
        limit: int | None = None,
        include_events: bool = False,
    ) -> list[MemoryRecord]:
        """Everything that currently holds, with no request to match against.

        Facts and procedures by default. An allergy or a policy is not something
        an agent searches for; it is something the agent always carries. Use this
        beside recall(), not instead of it:

            context = mem.standing() + mem.recall(user_message)

        Superseded memories are excluded, so this is the current picture.
        """
        if kind is not None:
            validate_kind(kind)
            kinds = [kind]
        elif include_events:
            kinds = None
        else:
            kinds = [SEMANTIC, PROCEDURAL]
        cap = int(limit or self.recall_cap)
        res = self.store.query(self.tenant, q.STANDING, {"kinds": kinds, "cap": cap})
        return [_record(r) for r in _rows(res)]

    def explain(self, memory_id: str) -> Provenance | None:
        """Why a memory exists: who wrote it, where, and what it came from."""
        rows = _rows(self.store.query(self.tenant, q.EXPLAIN, {"id": memory_id}))
        if not rows:
            return None
        r = rows[0]
        kinds = r.get("kinds") or []
        return Provenance(
            memory_id=r["id"],
            kind=next((k for k in kinds if k != "Memory"), "Memory"),
            text=r.get("text") or "",
            agent=r.get("agent") or "",
            session_id=r.get("session_id"),
            at=int(r.get("at") or 0),
            derived=bool(r.get("derived")),
            derived_from=[_record(e) for e in (r.get("derived_from") or []) if e],
            supersedes=[_record(o) for o in (r.get("supersedes") or []) if o],
        )

    # ---------------------------------------------------------------- coordinate

    def create_task(
        self, task: str, *, title: str | None = None, agent: str,
        subjects: tuple[str, ...] | list[str] = (),
    ) -> str:
        keys = []
        for name in subjects:
            key, _ = schema.resolve_subject(self.store, self.tenant, name)
            self.store.query(self.tenant, q.CREATE_SUBJECT, {"key": key, "name": name})
            keys.append(key)
        self.store.query(
            self.tenant, q.CREATE_TASK,
            {"task": task, "title": title, "agent": agent, "at": _now(), "subjects": keys},
        )
        return task

    def handoff(
        self, task: str, *, from_agent: str, to_agent: str,
        note: str | None = None, title: str | None = None,
    ) -> Handoff:
        """Record a task changing owner. The graph is the only channel."""
        hid = _rid("h")
        at = _now()
        self.store.query(
            self.tenant, q.HANDOFF,
            {"handoff_id": hid, "task": task, "from_agent": from_agent,
             "to_agent": to_agent, "note": note, "title": title, "at": at},
        )
        return Handoff(id=hid, task=task, from_agent=from_agent, to_agent=to_agent, at=at, note=note)

    def pick_up(self, task: str, *, agent: str | None = None) -> TaskContext | None:
        """Everything a receiving agent needs, from a tenant and a task id alone."""
        rows = _rows(self.store.query(self.tenant, q.PICK_UP, {"task": task}))
        if not rows:
            return None
        r = rows[0]
        return TaskContext(
            task=r["task"], title=r.get("title"), state=r.get("state") or "open",
            owner=r.get("owner"), handed_from=r.get("handed_from"),
            memories=[_record(m) for m in (r.get("memories") or []) if m],
        )

    # ---------------------------------------------- shared state (many agents)

    def join(self, task: str, *, agent: str) -> None:
        """Add an agent to a task without removing anyone else.

        This is how a swarm shares work. `handoff()` moves a single owner;
        `join()` is additive, so any number of agents work one task at once.
        """
        self.store.query(self.tenant, q.JOIN_TASK, {"task": task, "agent": agent, "at": _now()})

    def leave(self, task: str, *, agent: str) -> None:
        self.store.query(self.tenant, q.LEAVE_TASK, {"task": task, "agent": agent})

    def add_part(
        self, parent: str, part: str, *, title: str | None = None,
        subjects: tuple[str, ...] | list[str] = (),
    ) -> str:
        """Split a task into parts, so work can fan out across agents."""
        keys = []
        for name in subjects:
            key, _ = schema.resolve_subject(self.store, self.tenant, name)
            self.store.query(self.tenant, q.CREATE_SUBJECT, {"key": key, "name": name})
            keys.append(key)
        self.store.query(
            self.tenant, q.ADD_SUBTASK,
            {"parent": parent, "child": part, "title": title, "at": _now(), "subjects": keys},
        )
        return part

    def claim(self, task: str, *, agent: str) -> bool:
        """Try to take exclusive hold of a piece of work.

        Returns True to exactly one caller when several compete. A losing
        caller gets False and should move to the next unclaimed part.
        """
        res = self.store.query(self.tenant, q.CLAIM, {"task": task, "agent": agent, "at": _now()})
        return bool(res.result_set)

    def release(self, task: str, *, agent: str) -> None:
        self.store.query(self.tenant, q.RELEASE, {"task": task, "agent": agent, "at": _now()})

    def unclaimed_parts(self, parent: str, *, limit: int = 50) -> list[dict[str, Any]]:
        return _rows(self.store.query(self.tenant, q.UNCLAIMED_PARTS, {"parent": parent, "limit": int(limit)}))

    def in_flight(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Who is working on what, right now, across this tenant."""
        return _rows(self.store.query(self.tenant, q.IN_FLIGHT, {"limit": int(limit)}))

    def parts_status(self, parent: str) -> list[dict[str, Any]]:
        return _rows(self.store.query(self.tenant, q.PARTS_STATUS, {"parent": parent}))

    def set_task_state(self, task: str, state: str) -> None:
        self.store.query(self.tenant, q.SET_TASK_STATE, {"task": task, "state": state, "at": _now()})

    def open_tasks(self, *, limit: int = 20) -> list[dict[str, Any]]:
        return _rows(self.store.query(self.tenant, q.OPEN_TASKS, {"limit": int(limit)}))

    # ---------------------------------------------------------------- instruments

    def stats(self):
        from .metrics import read_stats

        return read_stats(self.store)

    def forget_everything(self) -> None:
        """Remove this tenant's whole memory. Other tenants are unaffected."""
        self.store.drop(self.tenant)
