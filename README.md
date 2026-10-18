# Auryn

**A FalkorDB-backed memory engine for AI agents**, and a crew of issue-triage
agents built on it.

Submission for **Track 02 — Agent Memory and Coordination**, WeMakeDevs
*Graph Hacks: Context for AI Agents*.

```bash
docker compose up -d
uv sync
uv run python -m demo.run --repo rohitrj22/auryn-triage-demo
```

**No API key. No signup. No configuration.** Point it at any public GitHub
repository and watch a crew of agents triage the open issues.

---

## The problem

Six issues arrive about the same bug. Six different agents work them. Each
reporter re-explains from scratch. Two agents fix the same thing. And when one
issue is closed as a duplicate, nobody can say why.

Three failures, and each one is a missing connection:

| Failure | The missing connection |
|---|---|
| Reporters repeat themselves | across **sessions** |
| The second agent does not know what the first learned | across **agents** |
| Nobody can explain the verdict | across **evidence** |

An agent with a context window cannot fix any of them. All three need memory
that outlives a process and is shared between agents.

## What this is

Two layers, with a hard boundary between them.

```
demo/        the agents              ──┐
demo/providers/  mock | gemini       ──┤── import auryn
proofs/      the five criteria       ──┤
examples/    bring your own agent    ──┘

auryn/       THE ENGINE.  No model. No embeddings. No generation.
             └──▶ FalkorDB
```

`auryn/` is the product. It carries no business vocabulary and no model code,
and two tests fail the build if either appears. The agents are the proof that
it works.

**Auryn is not an agent framework.** It owns your memory, not your loop.

| Auryn does | You keep |
|---|---|
| Store and recall three kinds of memory | Your model |
| Keep session history across restarts | Your prompts and context assembly |
| Isolate every tenant in its own graph | Your agent loop |
| Hold task state, handoffs and shared state | Your tools and routing |
| Explain why a memory exists | Your orchestration |

## Add memory to an agent you already have

Two lines around the model call you already wrote.

```python
from auryn import Memory, SEMANTIC

mem = Memory(tenant=user_id)                    # one isolated graph per user

def chat(user_message):
    context = mem.standing() + mem.recall(user_message)   # before your model
    reply = your_own_llm(context, user_message)           # your code, untouched
    mem.remember(SEMANTIC, a_fact_from(reply),            # after your model
                 agent="my-bot", subject="prefs")
    return reply
```

`standing()` returns what always applies, such as an allergy or a policy.
`recall()` adds what this message is about. Use both: a question worded
differently must not lose a standing fact.

A full worked example in a different domain is in
[`examples/bring_your_own_agent.py`](examples/bring_your_own_agent.py).

## The five criteria, as commands you can run

```bash
uv run python -m proofs.run_all      # 6/6 passed, no credentials needed
```

| Criterion | Proof | What it asserts |
|---|---|---|
| Episodic, semantic, procedural memory | `p2_memory_kinds` | 12 checks. Each kind recalled alone; a corrected belief kept and flagged; three events derive a fact linked to its evidence |
| Persistent conversation history | `p1_persistence` | Memories written in one process survive it exiting, and return in a new one with no history passed in |
| Shared state between agents | `p6_shared_state` | 8 agents, 10 parts, 0 duplicated work. 400 claim attempts produce exactly 25 winners. Agents read each other's findings mid-flight |
| Handoffs between agents | `p3_handoff` | A second process receives **two strings** and states facts it was never told |
| High-concurrency reads and writes | `p5_concurrency` | Engine operations and store queries reported separately, with the limiting factor named |
| Separate memory per tenant | `p4_isolation` | 1,000 graphs counted by `GRAPH.LIST`, 999 cross-tenant probes, 0 leaks |

### The graph has to do real work

Hackathon rule 3 says a graph drawn on top of ordinary storage does not
qualify. So one proof is designed to confirm a **failure**:

```bash
docker compose stop falkordb
uv run python -m proofs.p0_graph_required     # PASS = everything broke
docker compose start falkordb
```

Auryn cannot even be constructed without FalkorDB. There is no cache, no file
store, and no second database to fall back to.

## The graph data model

**One FalkorDB graph per tenant. The graph name is the tenant.** There is no
`tenant_id` property anywhere, so a query names one graph and cannot reach
another. Isolation is structural, not a `WHERE` clause.

Every memory carries two labels: the generic `Memory`, and its kind. So one
full-text index and one recall query serve all three kinds.

```
(:Session)──HAS_TURN──▶(:Turn)──NEXT──▶(:Turn)
     │
   PRODUCED
     ▼
(:Memory:Event)       something that happened, time is part of its meaning
(:Memory:Fact)        something that stays true, no expiry
(:Memory:Procedure)   how to act, carries the condition it applies under
     │
   ABOUT
     ▼
(:Subject)◀──RELATED_TO──▶(:Subject)        the hub every connection routes through
     ▲
  CONCERNS
     │
(:Task)──PART_OF──▶(:Task)                  work fans out into claimable parts
(:Agent)──OWNS────▶(:Task)                  one owner, moved by handoff
(:Agent)──WORKING_ON──▶(:Task)              many agents, additive
(:Handoff)──FROM/TO──▶(:Agent),  ──OF──▶(:Task)

(:Memory:Fact)──DERIVED_FROM──▶(:Memory:Event)    why the engine concluded it
(:Memory:Fact)──SUPERSEDES────▶(:Memory:Fact)     what it used to believe
(:Agent)──WROTE──▶(:Memory)                       who recorded it
```

`Subject` carries the whole design. A memory about one topic is reachable from
any other memory about that topic, and from a task about it. Remove `Subject`
and recall degrades to text search, while handoff stops working entirely.

Full detail: [`specs/001-agent-memory-engine/data-model.md`](specs/001-agent-memory-engine/data-model.md)

## The Cypher queries

Every query lives in one file, [`auryn/queries.py`](auryn/queries.py), and
nothing else in the codebase writes Cypher. Each is documented in
[`specs/001-agent-memory-engine/contracts/cypher.md`](specs/001-agent-memory-engine/contracts/cypher.md).

Every value passes as a parameter. No query is built by joining text.

**Recall** is one round trip. Full-text finds the starting nodes, the traversal
widens, and ranking is closeness first, then recency:

```cypher
CALL db.idx.fulltext.queryNodes('Memory', $terms) YIELD node AS seed, score
OPTIONAL MATCH (seed)-[:ABOUT]->(:Subject)-[:RELATED_TO*0..1]-(:Subject)<-[:ABOUT]-(near:Memory)
WITH collect({m: seed, s: score, h: 0}) + collect({m: near, s: score, h: 1}) AS rows
UNWIND rows AS row
WITH row.m AS m, row.s AS score, row.h AS hops
WHERE m IS NOT NULL
  AND ($kind IS NULL OR $kind IN labels(m))
  AND ($include_superseded OR coalesce(m.superseded, false) = false)
WITH m, min(hops) AS hops, max(score) AS score
RETURN m.id, labels(m) AS kinds, m.text, m.at, m.agent, m.session_id, hops, score
ORDER BY hops ASC, m.at DESC, score DESC
LIMIT $cap
```

**A handoff pickup** gives a receiving agent everything, from a tenant and a
task id alone:

```cypher
MATCH (t:Task {id: $task})
OPTIONAL MATCH (owner:Agent)-[:OWNS]->(t)
OPTIONAL MATCH (t)<-[:PART_OF*0..1]-(:Task)-[:CONCERNS]->(:Subject)<-[:ABOUT]-(m:Memory)
RETURN t.id, owner.name AS owner, collect(DISTINCT {text: m.text, agent: m.agent}) AS memories
```

**An atomic claim**, so two agents never work the same thing. The guard is in
the `WHERE`, so a losing claim returns zero rows:

```cypher
MATCH (t:Task {id: $task})
WHERE t.claimed_by IS NULL AND coalesce(t.state, 'open') = 'open'
SET   t.claimed_by = $agent, t.claimed_at = $at
RETURN t.id, t.claimed_by
```

### Two query details that would have been silent bugs

| Detail | Why it matters |
|---|---|
| Full-text terms for **recall** join with `\|` (OR); for **subject resolution** they are space-joined (AND) | With `item441`, `item442` and `item4410` present, `item\|441` matches all three and would merge them. `item 441` matches only `item441`. |
| A multi-word full-text query means AND by default | `'email refund'` returns nothing; `'email\|refund'` returns both. Recall would look broken for any multi-word question. |

## Measured

Every figure below comes from FalkorDB's own instruments — `GRAPH.LIST`,
`INFO memory`, `INFO latencystats`, `INFO commandstats` — not from a counter we
kept. Measured on an Apple-silicon laptop with the default container config
(`THREAD_COUNT=2`, `MAX_QUEUED_QUERIES=25`).

| Measurement | Result |
|---|---|
| Tenant graphs in one instance | **1,000**, counted by `GRAPH.LIST` |
| Time to create them | 20.9 s, about 48/sec |
| Instance memory | 13 MB → 1,106 MB, fully reclaimed on delete |
| **Cost per tenant** | **about 1,067 KB**, mostly its eight indexes |
| Cross-tenant leaks | **0** in 999 probes across 10 tenants |
| Round trips per `remember()` | **1** |
| Round trips per `recall()` | **1** |
| Recall at 5,000 stored memories | **4.6 ms** |
| Peak throughput, 8 processes | **995 engine ops/sec**, 1,046 store queries/sec |
| Claim atomicity | 400 attempts, **exactly 25 winners** in 25 rounds |
| Swarm correctness | 8 agents, 10 parts, **0 duplicated work** |

### How it scales with concurrency

Measured on a 12-core laptop. Load comes from several processes, because a
single Python process cannot saturate the server.

| Processes | Engine ops/sec | Store queries/sec | Server µs per query |
|---|---|---|---|
| 1 | 299 | 305 | 834 |
| 2 | 561 | 574 | 1,020 |
| 4 | 874 | 900 | 1,521 |
| **8** | **995** | 1,046 | 2,678 |
| 16 | 949 | 1,049 | 5,061 |

It scales to eight processes, then flattens because the load generator and the
database share twelve cores. Past that point the benchmark measures the laptop.

### Two optimisations, with the numbers that justified them

**1. Recall did not scale, and that was the serious one.**

The query applied its `LIMIT` *after* the traversal, so it expanded every
full-text match and only then trimmed to twenty. Cost grew with how much the
tenant remembered:

| Stored memories matching the query | Before | After |
|---|---|---|
| 100 | 14 ms | **1.2 ms** |
| 200 | 31 ms | **1.4 ms** |
| 800 | 312 ms | **1.4 ms** |
| 2,000 | **query timed out** | **2.3 ms** |
| 5,000 | — | **4.6 ms** |

Capping the seeds before the expansion made the cost independent of total
memory size. At 800 memories that is **220× faster**, and the timeout is gone.
[`tests/integration/test_recall_scales.py`](tests/integration/test_recall_scales.py)
fails if the regression returns.

**2. A write cost five round trips. Now it costs one.**

`remember()` used to resolve the subject, create it, write the memory, add its
kind label, and count siblings for the consolidation rule, as five separate
queries. They are now one, using a list-of-maps parameter for the subjects and
a running counter on the subject node instead of an O(n) re-count.

| | Before | After |
|---|---|---|
| Queries per `remember()` | 5 | **1** |
| Queries per `remember()` that derives a fact | 7 | 2 |
| Peak throughput | 578 ops/sec | **995 ops/sec** |

The container also raises `THREAD_COUNT` to 8 and `MAX_QUEUED_QUERIES` to 500,
because FalkorDB ships 2 and 25 and an agent memory layer is concurrent by
nature. Every proof prints the configuration it ran against, so no figure here
is detached from the settings that produced it.

### One bug this hunt uncovered

The schema bootstrap attempted all eight index creations on **every**
`Memory()` construction. They already existed, so FalkorDB rejected each one
and counted 2,800 `failed_calls` in a ten-second benchmark — corrupting the
very figure the benchmark reports. It now reads `db.indexes()` once and creates
only what is missing. Repeat openings issue no queries at all.

## Honest limits

Four things this does not do well. All are in the repo rather than discovered
by a reader.

1. **Recall matches words and connections, not meaning.** A question that
   shares no word with a memory and names no known subject will miss it. That
   is why agents should call `standing()` as well as `recall()`. FalkorDB ships
   a `vectorset` module, so adding similarity search is open, but it would need
   an embedding step and would break the zero-credential promise.
2. **Subject keys come from the caller.** The engine normalises them and
   resolves near matches with a full-text lookup, but it does not understand
   them. Proper entity resolution is out of scope.
3. **A graph per tenant is not free.** About 1 MB each, before any data. 1,000
   tenants fit on a laptop. 100,000 would not, and we are not going to pretend
   otherwise.
4. **Throughput past eight processes is machine-bound, not engine-bound.** The
   sweep above flattens because the load generator competes with the database
   for the same twelve cores. A separate host for each would measure the engine
   rather than the laptop, and we have not done that.

## How the demo works

```bash
# any public repo, no credentials
uv run python -m demo.run --repo rohitrj22/auryn-triage-demo

# offline and deterministic, which is what the proofs use
uv run python -m demo.run --inbox demo/data/inbox.json

# add one issue and watch it get recognised from memory
uv run python -m demo.run --new "note list empties after the app sits unused"
```

Five roles, all thin, all reaching memory only through Auryn:

| Agent | Job |
|---|---|
| **coordinator** | Splits the week into claimable parts |
| **investigator** ×6 | Claims a part, **reads shared memory first**, then works or defers |
| **triager** | Reads every finding, corrects a wrong one, hands the week over |
| **assignee** | Picks up with a tenant id and a task id, nothing else |
| **auditor** | Answers "why do you believe that?" from provenance alone |

On ten issues where five share one root cause, work is saved two ways:

```
claimed 10 of 10   investigated 6   recognised from memory 3   duplicated work 0
```

| Outcome | Mechanism |
|---|---|
| **deferred** | Lost the atomic claim on the *cause*, mid-flight |
| **skipped** | Read the finished cause from shared memory |

Each run writes a self-contained report to `output/triage-report.html` with the
verdicts, the agent timeline, the memory graph and the measured figures.

**See one without running anything:**
[sample report](https://htmlpreview.github.io/?https://github.com/rohitrj22/auryn/blob/main/docs/sample-report.html)
— produced by the command above against the live demo repository. The file is
[`docs/sample-report.html`](docs/sample-report.html), and it is self-contained:
no server, no network, no dependencies.

### Inspect the memory yourself

The FalkorDB Browser ships in the container:

**http://localhost:3000** — pick the graph named after your tenant.

```cypher
// why the engine believes several reports share one cause
MATCH (f:Memory:Fact {derived: true})-[:DERIVED_FROM]->(e:Memory:Event)
RETURN f.text AS conclusion, collect(e.text) AS evidence
```

## About the model provider

| | |
|---|---|
| **Default: `mock`** | Deterministic, offline, no credential. Its diagnosis is **scripted keyword scoring, not reasoning.** It exists so every proof is reproducible on any machine. |
| **With `GEMINI_API_KEY`** | `gemini-3.8-flash` does the diagnosis for real, and the model decides what is worth remembering. Nothing else changes. |

The engine cannot tell which one answered, and it never calls either.

```bash
cp .env.example .env    # then add your own key
```

Two details worth knowing: `gemini-2.5-flash` is retired for new keys and
returns 404, and `gemini-3.8-flash` spends output budget on thinking tokens, so
a tight output cap returns empty text.

## How it was built

Spec-first, using [GitHub Spec Kit](https://github.com/github/spec-kit). The
artifacts are in the repo because they are evidence, not paperwork:

| Document | What it holds |
|---|---|
| [`constitution.md`](.specify/memory/constitution.md) | Seven principles, three non-negotiable, each with a test that checks it |
| [`spec.md`](specs/001-agent-memory-engine/spec.md) | 6 user stories, 69 requirements, 22 success criteria |
| [`research.md`](specs/001-agent-memory-engine/research.md) | Ten findings, each verified against a live container rather than recalled |
| [`data-model.md`](specs/001-agent-memory-engine/data-model.md) | Every node, edge and index, with the reason it exists |
| [`plan.md`](specs/001-agent-memory-engine/plan.md) | Technical context, with measured figures |
| [`tasks.md`](specs/001-agent-memory-engine/tasks.md) | The task list and the cut order used under deadline |

## Setup

**Requirements:** a container runtime, Python 3.13 or newer, and `uv`.

```bash
docker compose up -d                 # FalkorDB on 6379, its Browser on 3000
uv sync --extra dev
uv run python -m proofs.run_all      # 6/6, no credentials
uv run python -m demo.run --repo rohitrj22/auryn-triage-demo
```

If port 6379 or 3000 is taken, set `AURYN_PORT` or `AURYN_UI_PORT`.

```bash
uv run pytest                        # unit and integration tests
```

## Disclosure

An AI coding assistant (Claude Code) was used throughout this project, as the
hackathon rules require disclosing. Every design decision, every measured
figure and every bug fix in the history was reviewed and directed by the
author, who can explain the graph model, the queries and the architecture.

All demonstration data is synthetic. The issues in
[`rohitrj22/auryn-triage-demo`](https://github.com/rohitrj22/auryn-triage-demo)
were written for this project and describe a fictional product.

## Licence

MIT
