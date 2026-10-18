# Contract: the engine's public surface

**Stability**: this is the contract the demo, the proofs and the eval harness
all depend on. Nothing else in `auryn/` is public.

```python
from auryn import Memory, EVENT, FACT, PROCEDURE

mem = Memory(tenant="t_acme")            # creates and indexes the graph if new
```

## `Memory(tenant, *, url=..., provider=None, consolidate_after=3, recall_cap=20)`

| Parameter | Default | Meaning |
|---|---|---|
| `tenant` | required | Becomes the graph name. Rejected if unsafe. |
| `url` | `falkor://localhost:6379` | Read from `FALKORDB_URL` when unset |
| `provider` | auto | `mock` unless `GEMINI_API_KEY` is set |
| `consolidate_after` | `3` | Events about one subject before a fact is derived (FR-016c) |
| `recall_cap` | `20` | Maximum rows any recall returns (FR-008) |

Opening a `Memory` is cheap. One connection is shared; the graph is chosen per
call (FR-055).

## `remember(kind, text, *, subject=None, subjects=(), agent, session=None, id=None, trigger=None) -> MemoryRecord`

Writes one memory. `kind` is one of the three constants.

- Returns a record carrying the assigned `id`.
- Writing an existing `id` updates in place and never duplicates (FR-005).
- A `Fact` that contradicts an earlier one marks the earlier `superseded` and
  links `[:SUPERSEDES]` (FR-004).
- Records the writing `agent` always (FR-025c).
- After writing an `Event`, checks the count rule and may derive a `Fact` (FR-016).

## `recall(query, *, kind=None, limit=None, include_superseded=False) -> list[MemoryRecord]`

Returns memories ranked by connection closeness, then recency (FR-009).

- `kind=None` returns all three kinds (FR-007). A kind filters to one (FR-006).
- One round trip to the store, always (FR-054).
- Empty result, never an error, when nothing matches (FR-010).
- Each record reports `session_id` and `agent`, so an answer is traceable (FR-011).

## `standing(*, kind=None, limit=None, include_events=False) -> list[MemoryRecord]`

Also note the shared-state operations below, added after this contract was
first written: `join`, `leave`, `add_part`, `claim`, `release`,
`unclaimed_parts`, `in_flight` and `parts_status`.

Everything that currently holds, with no request to match against. Facts and
procedures by default; events only when asked for. Superseded memories are
excluded.

**Use it beside `recall()`, not instead of it:**

```python
context = mem.standing() + mem.recall(user_message)
```

Why it exists: an allergy or a policy is not something an agent searches for.
It is something the agent always carries. Recall ranks by shared words and by
connection, so a question worded differently would miss it. A worked example
exposed this, and `standing()` is the fix.

## `handoff(task, *, from_agent, to_agent, note=None) -> Handoff`

Records a task changing owner (FR-017). The two agents exchange nothing
directly; the graph is the only channel (FR-019).

## `pick_up(task, *, agent) -> TaskContext`

The receiving half. Given only a tenant and a task id, returns every memory,
subject and turn connected to that task (FR-018). One round trip.

## Shared state: many agents on one task

`handoff()` moves a single owner, which models a relay. These model a swarm.

| Operation | Does |
|---|---|
| `join(task, *, agent)` | Adds an agent to a task. Additive, so it never removes another. |
| `leave(task, *, agent)` | Removes that agent only |
| `add_part(parent, part, *, title, subjects)` | Splits a task so work fans out |
| `claim(task, *, agent) -> bool` | **Exactly one caller gets True** when several compete. Measured atomic: 16 processes, 25 rounds, one winner each. |
| `release(task, *, agent)` | Gives a claimed part back |
| `unclaimed_parts(parent)` | What is still free to take |
| `in_flight()` | Who is working on what, right now |
| `parts_status(parent)` | Progress across every part, in one request |

Agents read each other's writes while still working, because `recall()` and
`standing()` never filter by agent. Measured: eight agents, one job, ten parts,
all ten completed once, zero duplicates, every finding readable by all.

## `history(*, session=None, limit=20) -> list[Turn] | list[Session]`

With `session`, returns that session's turns in order. Without it, lists the
tenant's past sessions, newest first (FR-014). Readable after the writing
process exits (FR-013).

## `start_session(*, agent) -> Session` and `end_session(session)`

Opens and closes a session. A session killed without closing keeps everything
written before that moment (edge case).

## `stats() -> Stats`

Reads FalkorDB's own instruments and returns them unchanged: server percentiles
from `INFO latencystats`, call and refusal counts from `INFO commandstats`,
instance memory from `INFO memory`, graph count from `GRAPH.LIST`. The engine
keeps no counters of its own (FR-048, and the plan's structure decision 2).

## Errors

| Condition | Behaviour |
|---|---|
| FalkorDB unreachable | Raises `StoreUnavailable`, naming the store. Never degrades to another store (FR-029). |
| Unsafe tenant name | Raises `InvalidTenant` before any query runs |
| Unknown kind | Raises `ValueError` |
| Text over the length limit | Stored truncated, with the truncation recorded. Never silent. |
| Provider returns empty text | Raises `ProviderFailure`. Memory already written is not rolled back, and this is distinguishable from an empty recall (edge case). |
