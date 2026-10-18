"""Every Cypher query Auryn depends on, in one place.

Nothing else in this codebase writes Cypher. Two reasons:
  1. "Always parameterized" becomes a single-file audit.
  2. Rule 10 asks us to publish the queries the product depends on.

Term semantics differ between two lookups, on purpose:
  recall  -> OR  (join with "|"). We want broad candidates; a miss is the cost.
  resolve -> AND (space-joined). We must never merge two different subjects.
"""

from __future__ import annotations

import re

_WORD = re.compile(r"[A-Za-z0-9]+")

# FalkorDB's full-text index treats a space as AND and "|" as OR.
RESERVED = {"and", "or", "not"}


def terms_or(text: str) -> str:
    """Words joined with '|' for recall. Broad on purpose."""
    words = [w.lower() for w in _WORD.findall(text or "") if len(w) > 1]
    words = [w for w in words if w not in RESERVED]
    return "|".join(dict.fromkeys(words))


def terms_and(text: str) -> str:
    """Words space-joined for subject resolution. Precise on purpose.

    Verified against a live index holding item441, item442 and item4410:
      "item|441" matched all three (scores 3, 1, 1)  <- would merge wrongly
      "item 441" matched only item441 (score 3)      <- correct
    """
    words = [w.lower() for w in _WORD.findall(text or "") if len(w) > 1]
    words = [w for w in words if w not in RESERVED]
    return " ".join(dict.fromkeys(words))


# ---------------------------------------------------------------- bootstrap

RANGE_INDEXES = (
    "CREATE INDEX FOR (s:Subject) ON (s.key)",
    "CREATE INDEX FOR (m:Memory)  ON (m.at)",
    "CREATE INDEX FOR (m:Memory)  ON (m.id)",
    "CREATE INDEX FOR (s:Session) ON (s.id)",
    "CREATE INDEX FOR (t:Task)    ON (t.id)",
    "CREATE INDEX FOR (a:Agent)   ON (a.name)",
)

FULLTEXT_INDEXES = (
    "CALL db.idx.fulltext.createNodeIndex('Memory','text')",
    "CALL db.idx.fulltext.createNodeIndex('Subject','name')",
)

LIST_INDEXES = "CALL db.indexes()"

# ---------------------------------------------------------------- sessions

START_SESSION = """
CREATE (s:Session {id: $id, started_at: $at, agent: $agent})
RETURN s.id AS id
"""

END_SESSION = """
MATCH (s:Session {id: $id}) SET s.ended_at = $at RETURN s.id AS id
"""

ADD_TURN = """
MATCH (s:Session {id: $session})
CREATE (t:Turn {id: $id, role: $role, text: $text, idx: $idx, at: $at})
CREATE (s)-[:HAS_TURN]->(t)
WITH s, t
OPTIONAL MATCH (s)-[:HAS_TURN]->(prev:Turn {idx: $idx - 1})
FOREACH (p IN CASE WHEN prev IS NULL THEN [] ELSE [prev] END |
  MERGE (p)-[:NEXT]->(t))
RETURN t.id AS id
"""

SESSION_TURNS = """
MATCH (:Session {id: $session})-[:HAS_TURN]->(t:Turn)
RETURN t.id AS id, t.role AS role, t.text AS text, t.idx AS idx, t.at AS at
ORDER BY t.idx ASC
"""

LIST_SESSIONS = """
MATCH (s:Session)
RETURN s.id AS id, s.started_at AS started_at, s.ended_at AS ended_at,
       s.agent AS agent
ORDER BY s.started_at DESC
LIMIT $limit
"""

# ---------------------------------------------------------------- subjects

# Precise lookup. AND semantics. Never merges two different subjects.
RESOLVE_SUBJECT = """
CALL db.idx.fulltext.queryNodes('Subject', $terms) YIELD node, score
RETURN node.key AS key, node.name AS name, score
ORDER BY score DESC
LIMIT 3
"""

CREATE_SUBJECT = """
MERGE (s:Subject {key: $key})
SET   s.name = coalesce(s.name, $name)
RETURN s.key AS key
"""

LINK_SUBJECTS = """
MATCH (a:Subject {key: $a}), (b:Subject {key: $b})
MERGE (a)-[:RELATED_TO]->(b)
RETURN a.key AS a, b.key AS b
"""

# ---------------------------------------------------------------- write

WRITE_MEMORY = """
MERGE (m:Memory {id: $id})
SET   m.text = $text, m.at = $at, m.subject_key = $subject_key,
      m.agent = $agent, m.session_id = $session_id,
      m.truncated = $truncated, m.derived = $derived,
      m.superseded = false, m.trigger = $trigger
WITH  m
CALL { WITH m
  UNWIND $subjects AS sk
    MERGE (s:Subject {key: sk})
    MERGE (m)-[:ABOUT]->(s)
}
WITH m
CALL { WITH m
  MATCH (sess:Session {id: $session_id})
  MERGE (sess)-[:PRODUCED]->(m)
}
MERGE (a:Agent {name: $agent})
MERGE (a)-[:WROTE]->(m)
RETURN m.id AS id
"""

# The kind label is added separately, because a label cannot be a parameter.
# The value is never user input; it comes from the KINDS tuple in models.py.
ADD_KIND_LABEL = "MATCH (m:Memory {{id: $id}}) SET m:{label} RETURN m.id AS id"

# ONE round trip for a whole write. It replaces five separate queries:
# resolve-adjacent subject creation, the memory write, the kind label, the
# session link, and the consolidation count.
#
# The {label} slot is filled from the KINDS tuple in models.py and is never
# user input. A label cannot be a query parameter in Cypher, so three
# pre-built variants exist rather than one built from a string at call time.
WRITE_MEMORY_ONE_SHOT = """
MERGE (m:Memory {{id: $id}})
SET   m:{label},
      m.text = $text, m.at = $at, m.subject_key = $subject_key,
      m.agent = $agent, m.session_id = $session_id,
      m.truncated = $truncated, m.derived = false,
      m.superseded = coalesce(m.superseded, false), m.trigger = $trigger
WITH m
CALL {{ WITH m
  UNWIND $subjects AS row
    MERGE (s:Subject {{key: row.k}})
    SET   s.name = coalesce(s.name, row.n)
    MERGE (m)-[:ABOUT]->(s)
}}
WITH m
CALL {{ WITH m
  MATCH (sess:Session {{id: $session_id}})
  MERGE (sess)-[:PRODUCED]->(m)
}}
WITH m
MERGE (a:Agent {{name: $agent}})
MERGE (a)-[:WROTE]->(m)
WITH m
CALL {{ WITH m
  UNWIND $old_ids AS oid
    MATCH (old:Memory {{id: oid}})
    WHERE old.id <> m.id AND coalesce(old.superseded, false) = false
    SET   old.superseded = true
    MERGE (m)-[:SUPERSEDES]->(old)
}}
WITH m
// Keep a running count ON the subject rather than re-counting its events.
// The scan this replaces was O(n) in events per subject, so every write got
// slower as memory grew. This is an indexed lookup and one property write.
MATCH (ps:Subject {{key: $subject_key}})
SET   ps.event_count = coalesce(ps.event_count, 0) + $event_delta
RETURN m.id AS id, ps.event_count AS events_on_subject
"""

# Supersession is ALWAYS explicit. The caller names the memories being
# replaced; the engine never infers it from a shared subject.
#
# Why: inferring it from a subject destroyed data. Two different facts about
# one subject ("allergic to peanuts", "allergic to shellfish") must coexist,
# and under parallel writes every agent superseded every other, leaving
# nothing standing. Guessing at contradiction needs a model, and this engine
# has none by design.
SUPERSEDE = """
UNWIND $old_ids AS oid
MATCH (old:Memory {id: oid})
WHERE old.id <> $new_id AND coalesce(old.superseded, false) = false
SET   old.superseded = true
WITH  collect(old) AS olds
MATCH (new:Memory {id: $new_id})
FOREACH (o IN olds | MERGE (new)-[:SUPERSEDES]->(o))
RETURN size(olds) AS superseded_count
"""

# ---------------------------------------------------------------- recall

# One round trip. Full-text finds starting points, traversal widens,
# ranking is closeness first, then recency, then text score.
RECALL = """
CALL db.idx.fulltext.queryNodes('Memory', $terms) YIELD node AS seed, score
// Cap the seeds BEFORE expanding. Without this, recall traverses every
// full-text match and only then applies LIMIT, so cost grows with how much
// the tenant remembers: 14 ms at 50 matches, 312 ms at 800, a timeout at
// 2000. Bounding the seeds makes the work independent of total memory size.
WITH seed, score ORDER BY score DESC LIMIT $seed_cap
WITH collect({m: seed, s: score, h: 0}) AS direct, collect(seed) AS seeds
CALL {
  WITH seeds
  UNWIND seeds AS sd
  MATCH (sd)-[:ABOUT]->(:Subject)-[:RELATED_TO*0..1]-(:Subject)<-[:ABOUT]-(near:Memory)
  WITH DISTINCT near
  LIMIT $near_cap
  RETURN collect({m: near, s: 0.0, h: 1}) AS nearby
}
WITH direct + nearby AS rows
UNWIND rows AS row
WITH row.m AS m, row.s AS score, row.h AS hops
WHERE m IS NOT NULL
  AND ($kind IS NULL OR $kind IN labels(m))
  AND ($include_superseded OR coalesce(m.superseded, false) = false)
WITH m, min(hops) AS hops, max(score) AS score
RETURN m.id AS id, labels(m) AS kinds, m.text AS text, m.at AS at,
       m.agent AS agent, m.session_id AS session_id,
       m.subject_key AS subject_key, coalesce(m.derived,false) AS derived,
       coalesce(m.superseded,false) AS superseded,
       coalesce(m.truncated,false) AS truncated, m.trigger AS trigger,
       hops, score
ORDER BY hops ASC, m.at DESC, score DESC
LIMIT $cap
"""

# Everything that currently holds, regardless of any request.
# Facts and procedures by default, because an allergy is not something you
# search for; it is something an agent always carries.
STANDING = """
MATCH (m:Memory)
WHERE ($kinds IS NULL OR any(k IN labels(m) WHERE k IN $kinds))
  AND coalesce(m.superseded, false) = false
RETURN m.id AS id, labels(m) AS kinds, m.text AS text, m.at AS at,
       m.agent AS agent, m.session_id AS session_id,
       m.subject_key AS subject_key, coalesce(m.derived,false) AS derived,
       coalesce(m.superseded,false) AS superseded,
       coalesce(m.truncated,false) AS truncated, m.trigger AS trigger,
       0 AS hops, 1.0 AS score
ORDER BY m.at DESC
LIMIT $cap
"""

RECALL_BY_SUBJECT = """
MATCH (s:Subject {key: $subject})<-[:ABOUT]-(m:Memory)
WHERE ($kind IS NULL OR $kind IN labels(m))
  AND ($include_superseded OR coalesce(m.superseded, false) = false)
RETURN m.id AS id, labels(m) AS kinds, m.text AS text, m.at AS at,
       m.agent AS agent, m.session_id AS session_id,
       m.subject_key AS subject_key, coalesce(m.derived,false) AS derived,
       coalesce(m.superseded,false) AS superseded,
       coalesce(m.truncated,false) AS truncated, m.trigger AS trigger,
       0 AS hops, 1.0 AS score
ORDER BY m.at DESC
LIMIT $cap
"""

# ---------------------------------------------------------------- consolidate

COUNT_EVENTS_FOR_SUBJECT = """
MATCH (e:Memory:Event)-[:ABOUT]->(:Subject {key: $subject})
RETURN count(e) AS n, collect(e.id)[0..$max] AS event_ids
"""

DERIVE_FACT = """
MERGE (f:Memory {id: $id})
SET   f:Fact, f.text = $text, f.at = $at, f.derived = true,
      f.subject_key = $subject, f.agent = $agent,
      f.session_id = $session_id, f.superseded = false, f.truncated = false
WITH  f
MERGE (s:Subject {key: $subject})
MERGE (f)-[:ABOUT]->(s)
WITH  f
CALL { WITH f
  UNWIND $event_ids AS eid
    MATCH (e:Memory {id: eid})
    MERGE (f)-[:DERIVED_FROM]->(e)
}
MERGE (a:Agent {name: $agent})
MERGE (a)-[:WROTE]->(f)
RETURN f.id AS id
"""

# ---------------------------------------------------------------- provenance

EXPLAIN = """
MATCH (m:Memory {id: $id})
OPTIONAL MATCH (m)-[:DERIVED_FROM]->(e:Memory)
OPTIONAL MATCH (m)-[:SUPERSEDES]->(o:Memory)
RETURN m.id AS id, labels(m) AS kinds, m.text AS text, m.at AS at,
       m.agent AS agent, m.session_id AS session_id,
       coalesce(m.derived,false) AS derived,
       collect(DISTINCT CASE WHEN e IS NULL THEN null ELSE
         {id:e.id, kinds:labels(e), text:e.text, at:e.at, agent:e.agent,
          session_id:e.session_id} END) AS derived_from,
       collect(DISTINCT CASE WHEN o IS NULL THEN null ELSE
         {id:o.id, kinds:labels(o), text:o.text, at:o.at, agent:o.agent,
          session_id:o.session_id} END) AS supersedes
"""

# ---------------------------------------------------------------- coordination

HANDOFF = """
MERGE (a:Agent {name: $from_agent})
MERGE (b:Agent {name: $to_agent})
MERGE (t:Task  {id: $task})
SET   t.updated_at = $at,
      t.state = coalesce(t.state, 'open'),
      t.title = coalesce(t.title, $title)
CREATE (h:Handoff {id: $handoff_id, at: $at, note: $note})
CREATE (h)-[:FROM]->(a)
CREATE (h)-[:TO]->(b)
CREATE (h)-[:OF]->(t)
WITH t, b
CALL { WITH t
  OPTIONAL MATCH (:Agent)-[r:OWNS]->(t) DELETE r
}
MERGE (b)-[:OWNS]->(t)
RETURN t.id AS task, b.name AS owner
"""

CREATE_TASK = """
MERGE (t:Task {id: $task})
SET   t.title = coalesce($title, t.title),
      t.state = coalesce(t.state, 'open'),
      t.created_at = coalesce(t.created_at, $at),
      t.updated_at = $at
WITH t
CALL { WITH t
  UNWIND $subjects AS sk
    MERGE (s:Subject {key: sk})
    MERGE (t)-[:CONCERNS]->(s)
}
MERGE (a:Agent {name: $agent})
MERGE (a)-[:OWNS]->(t)
RETURN t.id AS task
"""

SET_TASK_STATE = """
MATCH (t:Task {id: $task}) SET t.state = $state, t.updated_at = $at
RETURN t.id AS task, t.state AS state
"""

# Everything a receiving agent needs, from a tenant and a task id alone.
# ------------------------------------------------- shared state (many agents)

# Several agents work one task at the same time. This is additive, unlike
# OWNS, which handoff moves. A swarm joins; a relay hands over.
JOIN_TASK = """
MERGE (t:Task {id: $task})
SET   t.state = coalesce(t.state, 'open'), t.updated_at = $at
MERGE (a:Agent {name: $agent})
MERGE (a)-[w:WORKING_ON]->(t)
SET   w.since = coalesce(w.since, $at)
RETURN t.id AS task, a.name AS agent
"""

LEAVE_TASK = """
MATCH (:Agent {name: $agent})-[w:WORKING_ON]->(t:Task {id: $task})
DELETE w
RETURN t.id AS task
"""

# Work fans out. A parent task holds parts; each part can be claimed alone.
ADD_SUBTASK = """
MERGE (parent:Task {id: $parent})
SET   parent.state = coalesce(parent.state, 'open'), parent.updated_at = $at
MERGE (child:Task {id: $child})
SET   child.title = coalesce($title, child.title),
      child.state = coalesce(child.state, 'open'),
      child.created_at = coalesce(child.created_at, $at),
      child.updated_at = $at
MERGE (child)-[:PART_OF]->(parent)
WITH child
CALL { WITH child
  UNWIND $subjects AS sk
    MERGE (s:Subject {key: sk})
    MERGE (child)-[:CONCERNS]->(s)
}
RETURN child.id AS task
"""

# One agent wins a piece of work; the rest see it taken and move on.
# The guard is in the WHERE clause, so a losing claim returns zero rows.
# Measured atomic: 16 competing processes, 25 rounds, exactly one winner each.
CLAIM = """
MATCH (t:Task {id: $task})
WHERE t.claimed_by IS NULL AND coalesce(t.state, 'open') = 'open'
SET   t.claimed_by = $agent, t.claimed_at = $at, t.updated_at = $at
RETURN t.id AS task, t.claimed_by AS claimed_by
"""

RELEASE = """
MATCH (t:Task {id: $task})
WHERE t.claimed_by = $agent
SET   t.claimed_by = null, t.claimed_at = null, t.updated_at = $at
RETURN t.id AS task
"""

# Unclaimed parts of a parent task, so a worker knows what is left.
UNCLAIMED_PARTS = """
MATCH (child:Task)-[:PART_OF]->(:Task {id: $parent})
WHERE child.claimed_by IS NULL AND coalesce(child.state,'open') = 'open'
RETURN child.id AS task, child.title AS title
ORDER BY child.created_at ASC
LIMIT $limit
"""

# What every agent is doing right now, across the whole tenant.
IN_FLIGHT = """
MATCH (a:Agent)-[w:WORKING_ON]->(t:Task)
WHERE coalesce(t.state,'open') = 'open'
RETURN t.id AS task, t.title AS title, t.claimed_by AS claimed_by,
       collect(DISTINCT a.name) AS agents, max(w.since) AS since
ORDER BY since DESC
LIMIT $limit
"""

# Progress on a fanned-out task, read in one round trip.
PARTS_STATUS = """
MATCH (child:Task)-[:PART_OF]->(:Task {id: $parent})
RETURN coalesce(child.state,'open') AS state, count(*) AS n,
       collect(child.claimed_by)[0..5] AS claimed_by_sample
ORDER BY state
"""

PICK_UP = """
MATCH (t:Task {id: $task})
OPTIONAL MATCH (owner:Agent)-[:OWNS]->(t)
WITH t, owner
// The latest handoff wins. Collect SCALARS, never nodes: a collected node
// cannot be matched on, and an empty collect would yield a null node.
OPTIONAL MATCH (h:Handoff)-[:OF]->(t)
OPTIONAL MATCH (h)-[:FROM]->(prev:Agent)
WITH t, owner, coalesce(h.at, 0) AS hat, prev.name AS pname, h.note AS hnote
ORDER BY hat DESC
WITH t, owner, collect(pname)[0] AS handed_from, collect(hnote)[0] AS note
// Reach memories about this task AND about any of its parts, so a receiving
// agent sees everything the swarm learned, not only the parent's own subjects.
OPTIONAL MATCH (t)<-[:PART_OF*0..1]-(:Task)-[:CONCERNS]->(:Subject)<-[:ABOUT]-(m:Memory)
WHERE m IS NULL OR coalesce(m.superseded, false) = false
RETURN t.id AS task, t.title AS title, coalesce(t.state,'open') AS state,
       owner.name AS owner, handed_from, note,
       collect(DISTINCT CASE WHEN m IS NULL THEN null ELSE
         {id:m.id, kinds:labels(m), text:m.text, at:m.at, agent:m.agent,
          session_id:m.session_id, derived:coalesce(m.derived,false),
          trigger:m.trigger} END) AS memories
"""

OPEN_TASKS = """
MATCH (t:Task)
WHERE coalesce(t.state,'open') = 'open'
OPTIONAL MATCH (owner:Agent)-[:OWNS]->(t)
RETURN t.id AS task, t.title AS title, owner.name AS owner,
       t.updated_at AS updated_at
ORDER BY t.updated_at DESC
LIMIT $limit
"""
