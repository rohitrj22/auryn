# Auryn

A memory engine for AI agents, backed by FalkorDB.

Auryn gives agents three kinds of memory, a conversation history that survives
a restart, and shared state they read and write at the same time. Each tenant
gets its own graph, so one user's memory is unreachable from another's. Built
for **Track 02, Agent Memory and Coordination** of WeMakeDevs Graph Hacks.

The repo also ships the agents that prove it works: a triage crew you point at
any public GitHub repository.

Needs a container runtime, Python 3.13 or newer, and `uv`.

```bash
docker compose up -d        # FalkorDB on 6379, its Browser on 3000
uv sync --extra dev
uv run python -m demo.run --repo rohitrj22/auryn-triage-demo
```

No API key. GitHub's issues API is open for public repos, and the default model
provider runs locally.

[See a sample run](https://htmlpreview.github.io/?https://github.com/rohitrj22/auryn/blob/main/docs/sample-report.html)
without cloning anything.

## The problem

Six issues arrive about one bug. Six agents work them. Each reporter
re-explains from scratch, two agents fix the same thing, and nobody can say
why the duplicates were closed.

Each failure is a connection an agent with only a context window cannot make.

| Failure | Missing connection |
|---|---|
| Reporters repeat themselves | across sessions |
| One agent cannot see what another learned | across agents |
| Nobody can explain a verdict | across evidence |

## Verify the five criteria

```bash
uv run python -m proofs.run_all
```

Six proofs, no credentials. Each prints the numbers behind its verdict.

| Criterion | Proof | Asserts |
|---|---|---|
| Episodic, semantic, procedural memory | `p2_memory_kinds` | Each kind recalls alone. A corrected belief is kept and flagged. Three events derive a fact linked to its evidence. |
| Persistent conversation history | `p1_persistence` | Memories written in one process return in another, with no history passed in |
| Shared state between agents | `p6_shared_state` | 8 agents, 10 parts, zero duplicated work. 400 claim attempts, exactly 25 winners. Agents read each other mid-flight. |
| Handoffs between agents | `p3_handoff` | A second process gets two strings and states facts nobody told it |
| High-concurrency reads and writes | `p5_concurrency` | Engine operations and store queries counted separately, with the limit named |
| Separate memory per tenant | `p4_isolation` | 1,000 graphs counted by `GRAPH.LIST`, 999 cross-tenant probes, zero leaks |

### The graph has to do real work

Rule 3 says a graph drawn over ordinary storage does not qualify. So one proof
confirms a failure:

```bash
docker compose stop falkordb
uv run python -m proofs.p0_graph_required   # PASS means everything broke
docker compose start falkordb
```

Auryn cannot be constructed without FalkorDB. No cache, no file store, no
second database.

## Use it in your own agent

Auryn owns your memory, not your loop. It never calls a model, and it has no
opinion about your prompts, your tools, or your control flow.

```python
from auryn import Memory, SEMANTIC

mem = Memory(tenant=user_id)                  # one isolated graph per user

def chat(user_message):
    context = mem.standing() + mem.recall(user_message)
    reply = your_own_llm(context, user_message)
    mem.remember(SEMANTIC, a_fact_from(reply), agent="my-bot", subject="prefs")
    return reply
```

`standing()` returns what always applies, like an allergy or a policy.
`recall()` adds what this message is about. Use both, because a question worded
differently must not lose a standing fact.

[`examples/bring_your_own_agent.py`](examples/bring_your_own_agent.py) runs this
in a different domain.

## Graph data model

**One graph per tenant. The graph name is the tenant.** No node carries a
tenant id, so a query names one graph and cannot reach another. Isolation is
structural rather than a `WHERE` clause.

Every memory carries two labels, the generic `Memory` and its kind, so one
full-text index and one recall query serve all three kinds.

```
(:Session)──HAS_TURN──▶(:Turn)──NEXT──▶(:Turn)
     │
   PRODUCED
     ▼
(:Memory:Event)       something that happened; time is part of its meaning
(:Memory:Fact)        something that stays true; no expiry
(:Memory:Procedure)   how to act; carries its condition
     │
   ABOUT
     ▼
(:Subject)◀──RELATED_TO──▶(:Subject)
     ▲
  CONCERNS
     │
(:Task)──PART_OF──▶(:Task)          work fans out into claimable parts
(:Agent)──OWNS────▶(:Task)          one owner, moved by handoff
(:Agent)──WORKING_ON──▶(:Task)      many agents, additive
(:Handoff)──FROM/TO──▶(:Agent),  ──OF──▶(:Task)

(:Memory:Fact)──DERIVED_FROM──▶(:Memory:Event)   why the engine concluded it
(:Memory:Fact)──SUPERSEDES────▶(:Memory:Fact)    what it used to believe
(:Agent)──WROTE──▶(:Memory)                      who recorded it
```

`Subject` carries the design. A memory about one topic is reachable from every
other memory about it, and from a task about it. Remove `Subject` and recall
degrades to text search while handoff stops working.

Full detail in [`data-model.md`](specs/001-agent-memory-engine/data-model.md).

## The queries

Every query lives in [`auryn/queries.py`](auryn/queries.py), and nothing else
writes Cypher. Values always pass as parameters. Each query is documented in
[`contracts/cypher.md`](specs/001-agent-memory-engine/contracts/cypher.md).

Recall is one round trip. Full-text finds the seeds, the traversal widens, and
ranking is closeness first, then recency:

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

An atomic claim keeps two agents off the same work. The guard sits in the
`WHERE`, so a losing claim returns no rows:

```cypher
MATCH (t:Task {id: $task})
WHERE t.claimed_by IS NULL AND coalesce(t.state, 'open') = 'open'
SET   t.claimed_by = $agent, t.claimed_at = $at
RETURN t.id, t.claimed_by
```

Two query details that would have been silent bugs:

| Detail | Why it matters |
|---|---|
| Recall joins full-text terms with `\|` (OR). Subject resolution space-joins them (AND). | With `item441`, `item442` and `item4410` stored, `item\|441` matches all three and would merge them. `item 441` matches only `item441`. |
| A multi-word full-text query means AND by default | `'email refund'` returns nothing. `'email\|refund'` returns both. Recall would look broken for any multi-word question. |

## Measured

Every figure comes from FalkorDB's own instruments: `GRAPH.LIST`,
`INFO memory`, `INFO latencystats`, `INFO commandstats`. Measured on a 12-core
laptop with `THREAD_COUNT=8`, which the compose file sets.

| Measurement | Result |
|---|---|
| Tenant graphs in one instance | 1,000, counted by `GRAPH.LIST` |
| Time to create them | 20.9s, about 48 a second |
| Instance memory | 13 MB to 1,106 MB, fully reclaimed on delete |
| Cost per tenant | about 1,067 KB, mostly its indexes |
| Cross-tenant leaks | zero, in 999 probes across 10 tenants |
| Round trips per `remember()` and per `recall()` | 1 |
| Recall at 5,000 stored memories | 4.6 ms |
| Peak throughput, 8 processes | 995 engine operations a second |
| Claim atomicity | 400 attempts, exactly 25 winners in 25 rounds |

### Scaling with concurrency

| Processes | Engine ops/sec | Server µs per query |
|---|---|---|
| 1 | 299 | 834 |
| 2 | 561 | 1,020 |
| 4 | 874 | 1,521 |
| **8** | **995** | 2,678 |
| 16 | 949 | 5,061 |

It scales to eight processes, then flattens because the load generator and the
database share the same twelve cores. Past that point the benchmark measures
the laptop.

### Two fixes behind those numbers

Recall applied its `LIMIT` after the traversal, so it expanded every full-text
match before trimming. At 800 stored memories a recall took 312 ms, and at
2,000 it timed out. Capping the seeds before the expansion brought that to
1.4 ms and made cost independent of total memory.
[`test_recall_scales.py`](tests/integration/test_recall_scales.py) fails if it
returns. A write also cost five round trips and now costs one, which took peak
throughput from 578 operations a second to 995.

## Limits

1. **Recall matches words and connections, not meaning.** A question sharing no
   word with a memory and naming no known subject will miss it. Call
   `standing()` as well as `recall()`. FalkorDB ships a `vectorset` module, so
   similarity search is open, but it needs an embedding step and would end the
   zero-credential promise.
2. **Subject keys come from the caller.** Auryn normalises them and resolves
   near matches by full-text lookup, but it does not understand them. Entity
   resolution is out of scope.
3. **A graph per tenant costs about 1 MB before any data.** A thousand tenants
   fit on a laptop. A hundred thousand would not.
4. **Throughput past eight processes is machine-bound.** A separate host for the
   load generator would measure the engine instead of the laptop. We have not
   done that.
5. **The local provider scores keywords; it does not reason.** On ten purpose-written
   issues it groups correctly. Pointed at `falkordb/falkordb` it lumped 46 of 53
   real issues into 5 causes, which is too coarse to call triage. With a Gemini
   key the model does the diagnosis instead.

## The triage crew

```bash
uv run python -m demo.run --inbox demo/data/inbox.json     # offline
uv run python -m demo.run --new "notes vanish after the app idles"
```

| Agent | Job |
|---|---|
| coordinator | Splits the week into claimable parts |
| investigator (×6) | Claims a part, reads shared memory, then works or defers |
| triager | Reads every finding, corrects a wrong one, hands over |
| assignee | Picks up with a tenant id and a task id |
| auditor | Answers "why do you believe that?" from provenance |

On ten issues where five share a cause:

```
claimed 10 of 10   investigated 6   recognised from memory 3   duplicated work 0
```

A **deferred** agent lost the atomic claim on the cause mid-flight. A
**skipped** agent read the finished cause from shared memory. Each run writes
`output/triage-report.html`.

The FalkorDB Browser ships in the container at **http://localhost:3000**, so
you can read the memory graph directly. Pick the graph named after your tenant.

## Setup notes

### If port 6379 is taken

Shift the port and tell Auryn where to look. Both, not one:

```bash
AURYN_PORT=6380 AURYN_UI_PORT=3010 docker compose up -d
export FALKORDB_URL=falkor://localhost:6380
```

Auryn defaults to `falkor://localhost:6379`. If another Redis or Valkey answers
there, the error reads `Authentication required`, which points nowhere. Auryn
detects that case and prints the fix.

### With a real model

```bash
cp .env.example .env     # add your own GEMINI_API_KEY
```

The agents then use `gemini-3.8-flash` and the model decides what to remember.
Nothing else changes. Note that `gemini-2.5-flash` is retired for new keys and
returns 404, and `gemini-3.8-flash` spends output budget on thinking tokens, so
a tight output cap returns empty text.

## How it was built

Spec first, with [GitHub Spec Kit](https://github.com/github/spec-kit). The
[constitution](.specify/memory/constitution.md),
[specification](specs/001-agent-memory-engine/spec.md),
[research](specs/001-agent-memory-engine/research.md) and
[plan](specs/001-agent-memory-engine/plan.md) are in the repo because they are
evidence. Every finding in the research file was verified against a running
container.

## Disclosure

I used an AI coding assistant (Claude Code) throughout this project, as the
rules require me to disclose. I directed and reviewed every design decision,
measured figure and bug fix in the history. I can explain the graph model, the
queries and the architecture.

All demonstration data is synthetic. I wrote the issues in
[`rohitrj22/auryn-triage-demo`](https://github.com/rohitrj22/auryn-triage-demo)
for this project, and they describe a fictional product.

## Licence

MIT
