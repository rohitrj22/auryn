# Auryn

A memory engine for AI agents, backed by FalkorDB.

An AI agent forgets everything when its process stops, and it cannot see what
another agent learned. Auryn stores the agent's memory in a graph instead, so
it survives a restart and several agents can share it at once. Each user gets
their own graph, so one user's memory is unreachable from another's.

The repo also ships the agents that prove it works: a crew that triages the
open **GitHub issues** of any public repository. Those agents use
**Gemini (`gemini-3.8-flash`)** when you supply a key, and a local stand-in
when you do not.

Built for **Track 02, Agent Memory and Coordination**, of WeMakeDevs Graph Hacks.

```bash
docker compose up -d        # FalkorDB on 6379, its browser on 3000
uv sync --extra dev
uv run python -m demo.run --repo rohitrj22/auryn-triage-demo
```

No API key needed. GitHub's issues API is open for public repositories, and
the local provider needs no credential.

[See a sample run](https://htmlpreview.github.io/?https://github.com/rohitrj22/auryn/blob/main/docs/sample-report.html)
without cloning anything.

---

## The problem

Ten GitHub issues arrive. Six agents work them. Each reporter re-explains from
scratch, two agents investigate the same bug, and nobody can say why the
duplicates were closed.

Each failure is a connection an agent with only a context window cannot make.

| What goes wrong | What is not connected |
|---|---|
| A reporter explains the same thing twice | This week's conversation to last week's |
| Two agents investigate the same bug | One agent's findings to another agent's |
| Nobody can say why a verdict was reached | A conclusion to the evidence behind it |

---

## What Auryn stores, and why

Everything below exists to serve one of those three gaps. The definitions come
first, because the operations and the queries only make sense after them.

### Three kinds of memory

Auryn keeps three kinds apart, because they behave differently. These are the
standard **episodic**, **semantic** and **procedural** kinds. Auryn names them
for what they hold, so the same word appears in your Python and in the graph.

| Kind | Standard name | What it holds | Example from the triage crew | Why it is its own kind |
|---|---|---|---|---|
| **`EVENT`** | episodic | Something that happened, with a time | `issue #4 arrived and was reproduced` | The time is part of the meaning. **Counting events is how the crew notices that five issues share one cause.** |
| **`FACT`** | semantic | Something that stays true, with no expiry | `the token expires while the app is idle, and the first request after that is not retried` | An agent must **always** carry it, never search for it. A question worded differently must not lose it. |
| **`PROCEDURE`** | procedural | How to act, and the condition it applies under | `escalate a cause once five or more issues report it` with condition `reports>=5` | It carries a threshold, so **an agent reads the rule from memory and obeys it.** Change the memory and behaviour changes, with no code change. |

**Why split them at all?** An agent must always carry its facts and rules, but
only sometimes needs an old event. One undifferentiated pile makes that
impossible, because you cannot tell a standing rule from a stale incident.

### Topic: the piece that makes a graph worth using

Every memory is filed under one or more **topics**.

```
Event  "issue #4 arrived and was reproduced"  ──▶ topic "session-expiry"
Fact   "the token expires while idle"         ──▶ topic "session-expiry"
Task   "triage issue #4"                      ──▶ topic "session-expiry"
```

A topic is a **meeting point**. Two memories written by different agents, weeks
apart, in different sessions, attach to the same topic and become findable
together.

Remove topics and two things break at once. Recall degrades to a word search,
and handover stops working, because a task and a memory have nowhere to meet.

| Supporting piece | What it is | Which gap it closes |
|---|---|---|
| **Session** and **Turn** | One conversation, and each thing said in it, in order | Across sessions. A session stays readable after the process that wrote it exits. |
| **Agent** | A named writer. Every memory records who wrote it. | Across agents. Without it, "who decided this?" has no answer. |
| **Task** | One item of work, which can outlive a session and change hands | Across agents. A task is what gets handed over. |
| **Handoff** | The record of a task changing owner | Across agents, and it is a record rather than a message. Nothing is sent. |
| **Evidence link** | An arrow from a conclusion to the memories it came from | Across evidence. This is what makes "why do you believe that?" answerable. |
| **Supersede link** | An arrow from a new belief to the one it replaced | Across evidence. The old belief is kept and flagged, never deleted. |

---

## The operations Auryn supports

Nine operations. Each one serves a feature named above.

| Operation | What it does | What it is for |
|---|---|---|
| `remember(kind, text, topic=…)` | Writes one memory of one kind | All three kinds of memory |
| `recall(question)` | Finds the memories relevant to a question | Memory that reaches across sessions and agents |
| `standing()` | Returns every fact and rule that currently applies, with no question to match | So a rule is never missed because of how a question was worded |
| `explain(memory_id)` | Returns who wrote a memory, which conversation it came from, the evidence behind it, and what it replaced | Decisions that can be traced |
| `history(session=…)` | The turns of a conversation, in order | Conversation history that survives a restart |
| `handoff(task, from, to)` | Moves a task's single owner, and records the change | One agent takes over from another |
| `pick_up(task)` | Returns everything connected to a task, from a task id alone | The receiving agent needs no briefing |
| `join(task)` and `claim(item)` | Adds an agent to a task without removing anyone. Claiming takes exclusive hold of one item. | Many agents share one job without repeating work |
| `stats()` | Returns FalkorDB's own figures, unchanged | Honest measurement. The engine keeps no counters of its own. |

**Auryn is not an agent framework.** It owns your memory, not your loop. It
never calls a model. You keep your model, your prompts, your tools and your
control flow.

---

## Use it in your own agent

Three steps. Start FalkorDB, point Auryn at it, then add two lines around the
model call you already wrote.

### 1. Start FalkorDB

```bash
docker run -d -p 6379:6379 falkordb/falkordb:latest
```

That is the whole database side. No schema to create, no migration, no
per-user setup. Auryn builds its own indexes the first time it touches a
tenant's graph.

### 2. Point Auryn at it

```bash
pip install auryn                             # or: uv add auryn
export FALKORDB_URL=falkor://localhost:6379   # this is also the default
```

Or in code, if you would rather not use the environment:

```python
mem = Memory(tenant=user_id, url="falkor://localhost:6379")
```

Auryn opens one connection and reuses it. **`tenant` names the graph**, so
`Memory(tenant="alice")` reads and writes a FalkorDB graph called `alice`, and
`Memory(tenant="bob")` cannot reach it. That is the whole isolation mechanism.

### 3. Two lines in your agent

```python
from auryn import Memory, FACT

mem = Memory(tenant=user_id)     # connects, and creates the graph if new

def chat(user_message):
    # standing() carries what always applies: the facts and the rules.
    # recall() adds what this particular message is about.
    # Both, because a differently worded question must not lose a standing fact.
    context = mem.standing() + mem.recall(user_message)

    reply = your_own_llm(context, user_message)          # your code, untouched

    # A Fact, because a preference stays true. An Event would imply it expires.
    mem.remember(FACT, "prefers email over phone",
                 agent="my-bot", topic="contact")
    return reply
```

Picking the right kind is the only judgement the caller makes:

| You are storing | Use |
|---|---|
| Something that happened, which you may later want to count | `EVENT` |
| Something that stays true and should always be carried | `FACT` |
| A rule, with the condition it applies under | `PROCEDURE` |

[`examples/bring_your_own_agent.py`](examples/bring_your_own_agent.py) runs all
of this in a different domain.

### What Auryn does with FalkorDB on your behalf

So that a reader knows what they are getting, and what they are not.

| Auryn handles | You never write |
|---|---|
| Opening one pooled connection and reusing it | Connection code |
| Creating the graph for a new tenant on first use | A setup or migration step |
| Creating its eight indexes, once per tenant | Index definitions |
| Every Cypher query, all parameterised | Any Cypher |
| Choosing the graph per call from the tenant name | A tenant filter in a query |

If FalkorDB is unreachable, Auryn raises `StoreUnavailable` and names the port.
It has no second store, so it never answers from a cache instead.

---

## The graph, concretely

**One FalkorDB graph per tenant. The graph name is the tenant.** No node
carries a tenant id, so a query names one graph and cannot reach another.
Isolation is structural, not a `WHERE` clause a developer must remember.

Every memory carries two labels, the generic `Memory` and its kind, so one
index and one query serve all three kinds.

| Arrow | Reads as | Example |
|---|---|---|
| `(:Memory)-[:ABOUT]->(:Subject)` | this memory is about this topic | the 401 finding is about `session-expiry` |
| `(:Subject)-[:RELATED_TO]->(:Subject)` | these two topics are near each other | `session-expiry` relates to `token-refresh` |
| `(:Agent)-[:WROTE]->(:Memory)` | this agent recorded this | `investigator-1` wrote the 401 finding |
| `(:Session)-[:PRODUCED]->(:Memory)` | this memory came out of this conversation | |
| `(:Session)-[:HAS_TURN]->(:Turn)-[:NEXT]->(:Turn)` | the conversation, in order | |
| `(:Memory:Fact)-[:DERIVED_FROM]->(:Memory:Event)` | this conclusion came from these events | "five issues share this cause" points at all five |
| `(:Memory:Fact)-[:SUPERSEDES]->(:Memory:Fact)` | this belief replaced that one | the token-expiry answer replaced the platform-path answer |
| `(:Task)-[:PART_OF]->(:Task)` | this item belongs to that job | `triage-4` is part of `triage` |
| `(:Task)-[:CONCERNS]->(:Subject)` | this work is about this topic | **this arrow is what makes handover work** |
| `(:Agent)-[:OWNS]->(:Task)` | one owner, moved by handoff | |
| `(:Agent)-[:WORKING_ON]->(:Task)` | many agents, added without removing anyone | |
| `(:Handoff)-[:FROM\|TO]->(:Agent)`, `-[:OF]->(:Task)` | who passed what, and when | |

Full detail in [`data-model.md`](specs/001-agent-memory-engine/data-model.md).

---

## The queries

Every query lives in [`auryn/queries.py`](auryn/queries.py), and nothing else
in the codebase writes Cypher. Values always pass as parameters, so no text a
user typed can change a query's shape. Each one is documented in
[`contracts/cypher.md`](specs/001-agent-memory-engine/contracts/cypher.md).

Three of them carry the design.

### Recall, in one round trip

Find memories by words, step out to their topics and nearby topics, then rank
by closeness first and recency second.

```cypher
CALL db.idx.fulltext.queryNodes('Memory', $terms) YIELD node AS seed, score
WITH seed, score ORDER BY score DESC LIMIT $seed_cap
WITH collect({m: seed, s: score, h: 0}) AS direct, collect(seed) AS seeds
CALL {
  WITH seeds
  UNWIND seeds AS sd
  MATCH (sd)-[:ABOUT]->(:Subject)-[:RELATED_TO*0..1]-(:Subject)<-[:ABOUT]-(near:Memory)
  WITH DISTINCT near LIMIT $near_cap
  RETURN collect({m: near, s: 0.0, h: 1}) AS nearby
}
WITH direct + nearby AS rows
UNWIND rows AS row
WITH row.m AS m, row.s AS score, row.h AS hops
WHERE m IS NOT NULL
  AND ($kind IS NULL OR $kind IN labels(m))
  AND ($include_superseded OR coalesce(m.superseded, false) = false)
WITH m, min(hops) AS hops, max(score) AS score
RETURN m.id, labels(m) AS kinds, m.text, m.at, m.agent, hops, score
ORDER BY hops ASC, m.at DESC, score DESC
LIMIT $cap
```

Two parts matter. `LIMIT $seed_cap` on line 2 caps the work before the
traversal, so cost does not grow with how much a tenant remembers. And
`-[:RELATED_TO*0..1]-` means "zero or one steps along this arrow", which is the
thing a table database cannot express cheaply.

### Handover, from a task id alone

This is why `(:Task)-[:CONCERNS]->(:Subject)` exists. The receiving agent walks
from the job, down into its items, across to their topics, and back to every
memory about those topics.

```cypher
MATCH (t:Task {id: $task})
OPTIONAL MATCH (owner:Agent)-[:OWNS]->(t)
OPTIONAL MATCH (t)<-[:PART_OF*0..1]-(:Task)-[:CONCERNS]->(:Subject)<-[:ABOUT]-(m:Memory)
RETURN t.id, owner.name AS owner,
       collect(DISTINCT {text: m.text, agent: m.agent}) AS memories
```

### An atomic claim, so two agents never repeat work

The guard sits in the `WHERE`. If another agent already claimed it, the match
finds nothing and the query returns no rows, which the caller reads as "I lost".

```cypher
MATCH (t:Task {id: $task})
WHERE t.claimed_by IS NULL AND coalesce(t.state, 'open') = 'open'
SET   t.claimed_by = $agent, t.claimed_at = $at
RETURN t.id, t.claimed_by
```

## Benchmarks

Measured on a 12-core laptop. Every figure comes from FalkorDB's own
instruments: `GRAPH.LIST`, `INFO memory`, `INFO latencystats` and
`INFO commandstats`. The engine keeps no counters of its own.

### Tenant isolation at scale

| Measurement | Result |
|---|---|
| Tenant graphs in one instance | 1,000, counted by `GRAPH.LIST` |
| Time to create them | 20.9 s, about 48 a second |
| Instance memory | 13 MB to 1,106 MB |
| Cost per tenant | about 1,067 KB, mostly its eight indexes |
| Memory after deleting them | back to 13 MB, fully reclaimed |
| Cross-tenant reads that leaked | **0**, in 999 probes across 10 tenants |

### Recall

One round trip, whatever the question. Cost does not grow with how much a
tenant remembers.

| Stored memories matching the question | Before the fix | Now |
|---|---|---|
| 100 | 14 ms | **1.2 ms** |
| 800 | 312 ms | **1.4 ms** |
| 2,000 | query timed out | **2.3 ms** |
| 5,000 | not reached | **4.6 ms** |

The query applied its limit after the traversal, so it expanded every full-text
match before trimming. Capping the seeds first made the cost flat.
[`test_recall_scales.py`](tests/integration/test_recall_scales.py) fails if that
returns.

### Writes

| | Before | Now |
|---|---|---|
| Round trips per `remember()` | 5 | **1** |
| Round trips per `remember()` that derives a fact | 7 | 2 |
| Round trips per `recall()` and `standing()` | 1 | 1 |

### Throughput

Load comes from several processes, because one Python process cannot saturate
the server.

| Processes | Engine operations per second | Server µs per query |
|---|---|---|
| 1 | 299 | 834 |
| 2 | 561 | 1,020 |
| 4 | 874 | 1,521 |
| **8** | **995** | 2,678 |
| 16 | 949 | 5,061 |

It scales to eight processes, then flattens. Past that the load generator and
the database share the same twelve cores, so the benchmark measures the laptop.
Merging the write path took the peak from 578 to 995.

### Correctness under contention

| Measurement | Result |
|---|---|
| Agents racing for one claim | 16 processes, 25 rounds |
| Claim attempts | 400 |
| Winners | **exactly 25**, one per round |
| Swarm on one job | 8 agents, 10 parts, **0 duplicated work** |

Run them yourself:

```bash
uv run python -m proofs.isolation --tenants 1000
uv run python -m proofs.concurrency --procs 8 --seconds 15
uv run python -m proofs.shared_state
```

---

## Verify it yourself

```bash
uv run python -m proofs.run_all      # 6 of 6, no credentials needed
```

Each proof states one criterion, prints the numbers behind its verdict, and
exits non-zero on failure.

| Criterion | Command | What it asserts |
|---|---|---|
| Episodic, semantic, procedural memory | `proofs.memory_kinds` | Each kind recalls alone. A corrected belief is kept and flagged. Three events derive a fact linked to its evidence. |
| Persistent conversation history | `proofs.persistence` | Memories written in one process return in another, with no history passed in |
| Shared state between agents | `proofs.shared_state` | Agents read each other's findings while the others are still working |
| Handoffs between agents | `proofs.handoff` | A second process receives a tenant id and a task id, then states facts nobody told it |
| High-concurrency reads and writes | `proofs.concurrency` | Engine operations and store queries counted separately, with the limiting factor named |
| Separate memory per tenant | `proofs.isolation` | 1,000 graphs counted by `GRAPH.LIST`, 999 cross-tenant probes, zero leaks |

### The graph has to do real work

Hackathon rule 3 says a graph drawn over ordinary storage does not qualify. So
one proof confirms a **failure**.

```bash
docker compose stop falkordb
uv run python -m proofs.graph_required    # PASS means everything broke
docker compose start falkordb
```

Auryn cannot be constructed without FalkorDB. There is no cache, no file store
and no second database to fall back to.

---

## Setup notes

### If port 6379 is taken

Shift the port **and** tell Auryn where to look. Both, not one.

```bash
AURYN_PORT=6380 AURYN_UI_PORT=3010 docker compose up -d
export FALKORDB_URL=falkor://localhost:6380
```

Auryn defaults to `falkor://localhost:6379`. If another Redis or Valkey answers
there, the error reads `Authentication required`, which points nowhere. Auryn
detects that case and prints the fix.

### With Gemini

```bash
cp .env.example .env     # add your own GEMINI_API_KEY
```

The agents then use `gemini-3.8-flash`, and the model decides what is worth
remembering. Nothing else changes, and the engine cannot tell which provider
answered.

Two things to know. `gemini-2.5-flash` is retired for new keys and returns 404.
And `gemini-3.8-flash` spends output budget on thinking tokens, so a tight
output cap returns empty text.

Without a key, a local provider scores keywords. It is deterministic, so the
proofs give the same result every run. **It does not reason.** On the ten
purpose-written issues it groups correctly. Pointed at a large real repository
it is too coarse to call triage.

---

## How it was built, and disclosure

Spec first, with [GitHub Spec Kit](https://github.com/github/spec-kit). The
[constitution](.specify/memory/constitution.md),
[specification](specs/001-agent-memory-engine/spec.md),
[research](specs/001-agent-memory-engine/research.md) and
[plan](specs/001-agent-memory-engine/plan.md) are in the repo because they are
evidence. Every finding in the research file was verified against a running
container.

I used an AI coding assistant throughout this project, as the rules require me
to disclose. I directed and reviewed every design decision, measured figure and
bug fix in the history.

All demonstration data is synthetic. I wrote the issues in
[`rohitrj22/auryn-triage-demo`](https://github.com/rohitrj22/auryn-triage-demo)
for this project, and they describe a fictional product.

## Licence

MIT
