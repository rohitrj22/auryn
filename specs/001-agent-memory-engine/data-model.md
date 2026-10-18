# Data Model: Auryn

**Date**: 2026-10-18. Every structure below was checked against a live FalkorDB
8.10.2 container.

## The isolation boundary

**One FalkorDB graph per tenant. The graph name is the tenant identity.**

There is no `Tenant` node and no `tenant_id` property on any node. A tenant's
memory is unreachable from another tenant's graph, because a query names one
graph and cannot span two. This satisfies FR-021 and Constitution Principle I's
rule that isolation must not rest on a `WHERE` clause.

```
FalkorDB instance
├── graph "t_acme"      ← one tenant's whole memory
├── graph "t_globex"    ← another, unreachable from the first
└── graph "t_initech"
```

Verified: `GRAPH.LIST` returned 1,000 such graphs; a read in one returned 0 rows
for another's data.

## Node labels

Every memory carries two labels: the generic `Memory`, and its kind. Verified
working:

```
MATCH (m:Memory)        → all three kinds
MATCH (m:Memory:Fact)   → facts only
```

This is what lets one full-text index and one recall query serve all three
kinds, instead of three of each.

### `(:Memory:Event)` — something that happened

| Property | Type | Notes |
|---|---|---|
| `id` | string | Stable identifier, used for deduplication (FR-005) |
| `text` | string | What happened, as written |
| `at` | integer | Epoch milliseconds. The time it happened. |
| `subject_key` | string | The main subject, for fast filtering |
| `agent` | string | Which agent wrote it (FR-025c) |
| `session_id` | string | The session it arose in (FR-002) |

### `(:Memory:Fact)` — something held to stay true

| Property | Type | Notes |
|---|---|---|
| `id` | string | |
| `text` | string | |
| `at` | integer | When it was recorded, not a limit on its truth |
| `subject_key` | string | |
| `agent` | string | |
| `session_id` | string | |
| `derived` | boolean | `true` when the engine concluded it (FR-016b) |
| `superseded` | boolean | `true` when a newer fact replaced it (FR-004) |

### `(:Memory:Procedure)` — how to carry out a task

| Property | Type | Notes |
|---|---|---|
| `id`, `text`, `at`, `subject_key`, `agent`, `session_id` | | As above |
| `trigger` | string | The condition under which it applies |

### Supporting nodes

| Label | Properties | Purpose |
|---|---|---|
| `(:Subject)` | `key`, `name` | What memories are about. The hub that makes traversal work. |
| `(:Session)` | `id`, `started_at`, `ended_at` | One conversation (FR-012 to FR-014) |
| `(:Turn)` | `id`, `role`, `text`, `idx`, `at` | One utterance, with its position |
| `(:Agent)` | `name` | A named writer and task owner |
| `(:Task)` | `id`, `title`, `state`, `created_at`, `updated_at` | Work that outlives a session |
| `(:Handoff)` | `id`, `at`, `note` | The record of a task changing owner |

## Relationships

```
(:Session)-[:HAS_TURN]->(:Turn)
(:Turn)-[:NEXT]->(:Turn)                     ordered chain within a session
(:Session)-[:PRODUCED]->(:Memory)
(:Memory)-[:ABOUT]->(:Subject)               the traversal backbone
(:Subject)-[:RELATED_TO]->(:Subject)         lets recall reach one hop further
(:Memory:Fact)-[:DERIVED_FROM]->(:Memory:Event)   consolidation provenance (FR-016a)
(:Memory:Fact)-[:SUPERSEDES]->(:Memory:Fact)      correction history (FR-004)
(:Agent)-[:WROTE]->(:Memory)
(:Agent)-[:OWNS]->(:Task)
(:Task)-[:CONCERNS]->(:Subject)
(:Session)-[:FOR_TASK]->(:Task)
(:Handoff)-[:FROM]->(:Agent)
(:Handoff)-[:TO]->(:Agent)
(:Handoff)-[:OF]->(:Task)
```

### Why `Subject` exists

Without it, recall can only match text. With it, a memory about "order 441" is
reachable from any other memory about "order 441", and from a related subject
one hop away. That traversal is what FR-009 ranks by, and it is the reason a
graph beats a list of notes here.

```
(:Memory:Event {text:"order 441 arrived damaged"})-[:ABOUT]->(:Subject {key:"order441"})
(:Memory:Fact  {text:"replacement shipped"})      -[:ABOUT]->(:Subject {key:"order441"})
(:Subject {key:"order441"})-[:RELATED_TO]->(:Subject {key:"contact"})
```

## Indexes

Created by `auryn/schema.py` when a tenant graph is first touched.

| Index | On | Why | Verified |
|---|---|---|---|
| Range | `(:Subject) ON (key)` | Every recall resolves subjects first | `CREATE INDEX FOR (s:Subject) ON (s.key)` → `Indices created: 1` |
| Range | `(:Memory) ON (at)` | Recency is the second ranking term | Same form |
| Range | `(:Memory) ON (id)` | Deduplication on write (FR-005) | Same form |
| Range | `(:Session) ON (id)` | History lookup | Same form |
| Range | `(:Task) ON (id)` | Handoff lookup (FR-018) | Same form |
| Full-text | `(:Memory) ON (text)` | Resolves free text to starting nodes | `CALL db.idx.fulltext.createNodeIndex('Memory','text')` → `Indices created: 1` |

`CALL db.indexes()` confirms both kinds, reporting `{subject: [RANGE]}` and
`{text: [FULLTEXT]}` with `language: english`.

**One behaviour to code around.** A multi-word full-text query means AND by
default, so unrelated terms match nothing:

```
queryNodes('Memory','email refund')   → 0 rows
queryNodes('Memory','email|refund')   → 2 rows
```

So `auryn/queries.py` splits the request into terms and joins them with `|`.
This was found by probing, and it would have been a silent empty-recall bug.

## Validation rules

Drawn from the functional requirements, enforced in `auryn/models.py`.

| Rule | Source |
|---|---|
| A memory has exactly one kind of the three | FR-001 |
| `tenant_id` must be safe as a graph name, else rejected | Edge case: unexpected characters |
| `text` has a stated maximum length; truncation is recorded, never silent | Edge case: very long statement |
| Writing an existing `id` updates, and never creates a second node | FR-005 |
| A recall returns at most a stated cap | FR-008 |
| `derived` is true only on a fact the engine concluded | FR-016b |
| A superseded fact is kept and flagged, never deleted | FR-004 |
| Every memory records its writing agent | FR-025c |

## State transitions

**`Fact`**

```
current ──(a contradicting fact arrives)──> superseded
            the new fact gets [:SUPERSEDES] to the old one
```
A superseded fact stays readable. Recall excludes it from current answers but
can return it when history is asked for.

**`Task`**

```
open ──[:HANDOFF]──> open (new owner) ──> done
                 └──────────────────────> abandoned
```
A task handed to an agent that never runs stays `open` with a named owner. It
never becomes lost, which the edge case requires.

**`Event` to `Fact`, by the count rule (FR-016)**

```
Events about the same Subject accumulate.
When the count reaches the threshold (default stated in config),
the engine writes (:Memory:Fact {derived:true})
and links [:DERIVED_FROM] to every contributing Event.
```
No language model takes part, so this works with zero credentials and is
testable by counting.

## Full worked example

One tenant, after two sessions, as the demo produces it.

```cypher
// Session 1, Triage agent
CREATE (s1:Session {id:'s1', started_at:1760000000000})
CREATE (t1:Turn {id:'t1', role:'user', idx:0, text:'my order 441 arrived damaged'})
CREATE (s1)-[:HAS_TURN]->(t1)
CREATE (e1:Memory:Event {id:'e1', text:'order 441 arrived damaged',
                         at:1760000000000, subject_key:'order441',
                         agent:'triage', session_id:'s1'})
CREATE (sub:Subject {key:'order441', name:'Order 441'})
CREATE (e1)-[:ABOUT]->(sub)
CREATE (s1)-[:PRODUCED]->(e1)
CREATE (a:Agent {name:'triage'})-[:WROTE]->(e1)
CREATE (task:Task {id:'k1', title:'damaged order 441', state:'open'})
CREATE (a)-[:OWNS]->(task)
CREATE (task)-[:CONCERNS]->(sub)

// Handoff to the Refund agent. No message passes between them.
CREATE (b:Agent {name:'refund'})
CREATE (h:Handoff {id:'h1', at:1760000001000})
CREATE (h)-[:FROM]->(a), (h)-[:TO]->(b), (h)-[:OF]->(task)

// Session 2, days later, new process, empty prompt.
// The Refund agent knows everything from the graph alone.
MATCH (tk:Task {id:$task})-[:CONCERNS]->(sub:Subject)<-[:ABOUT]-(m:Memory)
RETURN labels(m) AS kind, m.text AS text, m.agent AS written_by, m.at AS at
ORDER BY m.at DESC
```

That last query is the handoff proof in one round trip, which is what FR-054
requires.
