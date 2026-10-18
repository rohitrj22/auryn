# Contract: every query the product depends on

**Status, 2026-10-18.** Two queries listed below were merged into one and no
longer exist as separate statements:

| Was | Now |
|---|---|
| `WRITE_MEMORY` plus `ADD_KIND_LABEL` plus the subject writes plus the sibling count | `WRITE_MEMORY_ONE_SHOT`, one round trip |
| `SUPERSEDE` | Folded into that same query, driven by an explicit `$old_ids` list |

`RECALL` also gained `LIMIT $seed_cap` before its traversal. Without it, recall
expanded every full-text match before trimming, so cost grew with how much a
tenant remembered: 14 ms at 100 memories, 312 ms at 800, and a timeout at 2,000.

[`auryn/queries.py`](../../../auryn/queries.py) is the source of truth.

Rule 10 requires publishing these. They all live in `auryn/queries.py`, and
nothing else in the codebase writes Cypher. Every value is a parameter; no query
is assembled by joining text (FR-052).

## Bootstrap a tenant graph

```cypher
CREATE INDEX FOR (s:Subject) ON (s.key)
CREATE INDEX FOR (m:Memory)  ON (m.at)
CREATE INDEX FOR (m:Memory)  ON (m.id)
CREATE INDEX FOR (s:Session) ON (s.id)
CREATE INDEX FOR (t:Task)    ON (t.id)
CALL db.idx.fulltext.createNodeIndex('Memory','text')
```

## Write a memory, with deduplication and subject linking

```cypher
MERGE (m:Memory {id: $id})
SET   m:Event,
      m.text = $text, m.at = $at, m.subject_key = $subject_key,
      m.agent = $agent, m.session_id = $session_id
WITH  m
UNWIND $subjects AS sk
  MERGE (s:Subject {key: sk})
  MERGE (m)-[:ABOUT]->(s)
WITH  m
MATCH (sess:Session {id: $session_id})
MERGE (sess)-[:PRODUCED]->(m)
MERGE (a:Agent {name: $agent})
MERGE (a)-[:WROTE]->(m)
RETURN m.id AS id
```

`MERGE` on `id` is what makes a repeat write an update (FR-005). The label is
added with `SET m:Event` so the generic `Memory` label is always present too.

## Recall: full-text to find starting points, then traverse, then rank

This is the single query FR-054 requires. One round trip.

```cypher
CALL db.idx.fulltext.queryNodes('Memory', $terms) YIELD node AS seed, score
MATCH (seed)-[:ABOUT]->(s:Subject)
OPTIONAL MATCH (s)-[:RELATED_TO*0..1]-(s2:Subject)<-[:ABOUT]-(m:Memory)
WITH DISTINCT coalesce(m, seed) AS m, score,
     CASE WHEN m = seed THEN 0 ELSE 1 END AS hops
WHERE ($kind IS NULL OR $kind IN labels(m))
  AND ($include_superseded OR coalesce(m.superseded, false) = false)
RETURN m.id AS id, labels(m) AS kinds, m.text AS text, m.at AS at,
       m.agent AS agent, m.session_id AS session_id, hops, score
ORDER BY hops ASC, m.at DESC, score DESC
LIMIT $cap
```

`$terms` is the request's words joined with `|`. **This matters:** a multi-word
full-text query means AND by default, so `'email refund'` returns nothing while
`'email|refund'` returns both. Verified by probe.

Ranking order is `hops` first, then recency, then text score. That is FR-009's
"closeness first, recency second".

## Recall one kind only

The query above with `$kind` set to `'Event'`, `'Fact'`, or `'Procedure'`
(FR-006). `$kind IN labels(m)` works because every memory carries two labels.

## Derive a fact from repeated events (the count rule)

```cypher
MATCH (e:Memory:Event)-[:ABOUT]->(s:Subject {key: $subject_key})
WITH s, count(e) AS n, collect(e) AS events
WHERE n >= $threshold
MERGE (f:Memory {id: $derived_id})
SET   f:Fact, f.text = $text, f.at = $at, f.derived = true,
      f.subject_key = $subject_key, f.agent = $agent
MERGE (f)-[:ABOUT]->(s)
WITH  f, events
UNWIND events AS e
  MERGE (f)-[:DERIVED_FROM]->(e)
RETURN f.id AS id, size(events) AS from_events
```

Counting only. No model takes part (FR-016).

## Supersede a contradicted fact

```cypher
MATCH (old:Memory:Fact {subject_key: $subject_key})
WHERE coalesce(old.superseded, false) = false AND old.id <> $new_id
SET   old.superseded = true
WITH  old
MATCH (new:Memory:Fact {id: $new_id})
MERGE (new)-[:SUPERSEDES]->(old)
RETURN count(old) AS superseded_count
```

The old fact is kept and flagged, never deleted (FR-004).

## Record a handoff

```cypher
MERGE (a:Agent {name: $from_agent})
MERGE (b:Agent {name: $to_agent})
MERGE (t:Task  {id: $task})
SET   t.updated_at = $at, t.state = 'open'
CREATE (h:Handoff {id: $handoff_id, at: $at, note: $note})
CREATE (h)-[:FROM]->(a), (h)-[:TO]->(b), (h)-[:OF]->(t)
WITH  t, b
OPTIONAL MATCH (:Agent)-[r:OWNS]->(t) DELETE r
MERGE (b)-[:OWNS]->(t)
RETURN t.id AS task, b.name AS owner
```

## Pick up a handed-off task

Everything the receiving agent needs, from a tenant and a task id alone
(FR-018). One round trip.

```cypher
MATCH (t:Task {id: $task})
OPTIONAL MATCH (t)-[:CONCERNS]->(s:Subject)<-[:ABOUT]-(m:Memory)
OPTIONAL MATCH (owner:Agent)-[:OWNS]->(t)
OPTIONAL MATCH (h:Handoff)-[:OF]->(t)
OPTIONAL MATCH (h)-[:FROM]->(prev:Agent)
RETURN t.id AS task, t.title AS title, t.state AS state,
       owner.name AS owner, prev.name AS handed_from,
       collect(DISTINCT {kinds: labels(m), text: m.text,
                         at: m.at, agent: m.agent}) AS memories
ORDER BY t.updated_at DESC
```

## Session history

```cypher
MATCH (s:Session {id: $session})-[:HAS_TURN]->(t:Turn)
RETURN t.role AS role, t.text AS text, t.idx AS idx, t.at AS at
ORDER BY t.idx ASC
```

```cypher
MATCH (s:Session)
RETURN s.id AS id, s.started_at AS started_at, s.ended_at AS ended_at
ORDER BY s.started_at DESC
LIMIT $limit
```

## Instruments — read, never computed by us

These are commands, not Cypher, and they are the source of every published
number.

| Command | Gives |
|---|---|
| `GRAPH.LIST` | The tenant graph count (FR-048) |
| `INFO memory` | Instance memory, and the per-tenant delta (FR-049) |
| `GRAPH.MEMORY USAGE <g>` | Component breakdown: label matrices, relation matrices, node blocks, attributes, index size. **Rounds to whole MB**, so it cannot measure one small graph. |
| `INFO latencystats` | `p50`, `p99`, `p99.9` per command (FR-043) |
| `INFO commandstats` | `calls`, `usec_per_call`, `rejected_calls`, `failed_calls` (FR-044) |
| `GRAPH.CONFIG GET *` | The configuration a run used (FR-045) |
| `GRAPH.PROFILE <q>` | The execution plan with per-operator timing (FR-051) |
| result `run_time_ms` | Server-side time for that one query (FR-041) |
