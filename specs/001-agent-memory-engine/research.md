# Phase 0 Research: Auryn

**Date**: 2026-10-18. Every finding below was verified against a live FalkorDB
8.10.2 container, not recalled from memory. Commands and outputs are exact.

## R1. How recall ranks relevance

**Decision**: Resolve the subjects a request names with FalkorDB's full-text
index, then follow links from those subjects up to two hops, then rank by
connection closeness first and recency second. All of it in one query.

**Rationale**: The original plan for FR-009 had a known weakness. Pure subject
matching fails when the request uses words that match no stored subject. The
probe found that FalkorDB ships a full-text index, which removes that weakness
without any embedding step and without any credential.

Verified:

```
GRAPH.QUERY tenant_a "CALL db.idx.fulltext.createNodeIndex('Fact','text')"
→ Indices created: 1

GRAPH.QUERY tenant_a "CALL db.idx.fulltext.queryNodes('Fact','damaged')
                      YIELD node, score RETURN node.text, score"
→ "order 441 arrived damaged" | 4
→ Query internal execution time: 0.159458 milliseconds
```

So free text in, scored nodes out, in 0.16 ms, offline. Those scored nodes
become the starting points for the traversal.

**Alternatives considered**:

- *Meaning-based similarity.* The container does load a `vectorset` module
  (ver 1), so the storage half is free. The cost is producing the numbers:
  an embedding call per memory, which breaks the zero-credential rule unless we
  write an offline stand-in. Deferred. The eval harness exists so this can be
  revisited with data.
- *Recency only.* Trivial to build and genuinely weak. Rejected.
- *Exact subject match only.* The original option A. Superseded by the full-text
  finding above, which strictly improves it at no cost.

## R2. Index support and its effect

**Decision**: Create a range index on every field recall filters on, and a
full-text index on every field recall searches as text. Build them in
`auryn/schema.py` at tenant bootstrap.

Verified:

```
GRAPH.QUERY tenant_a "CREATE INDEX FOR (f:Fact) ON (f.subject)"
→ Indices created: 1

GRAPH.QUERY tenant_a "CALL db.indexes()"
→ Fact | [subject] | {subject: [RANGE]}
```

`GRAPH.PROFILE` reports the plan with per-operator timing, which is what FR-051
needs:

```
GRAPH.PROFILE tenant_a "MATCH (f:Fact) RETURN f"
→ Results | Records produced: 1, Execution time: 0.000083 ms
→     Project | Records produced: 1, Execution time: 0.004625 ms
→         Node By Label Scan | (f:Fact) | Records produced: 1, Execution time: 0.000875 ms
```

The `Node By Label Scan` line is the "before" picture. After indexing, the same
query plan reports an index scan instead. Both go in the README.

**Alternatives considered**: no indexes, relying on small graphs. Rejected.
It would make the speed numbers meaningless and waste the strongest evidence we
can offer that the work was done properly.

## R3. Parameterized queries and the plan cache

**Decision**: Every query passes values as parameters. `auryn/queries.py` holds
every Cypher string and nothing else in the codebase writes Cypher.

Verified, with the Python client:

```python
g.query("CREATE (:Event {text:$t, subject:$s, at:$a})",
        params={"t": ..., "s": ..., "a": ...})
```

Every result carries a `Cached execution:` line, `0` on a first run and `1` on
a reuse, so FR-053 is satisfied by FalkorDB's own output. `CACHE_SIZE` is 25 by
default, which comfortably covers the engine's fixed set of queries.

This also matters for safety, not only speed. Tenant and subject values never
enter query text, so no input can alter a query's shape.

## R4. One connection, one graph per tenant

**Decision**: Hold one `FalkorDB` client and call `select_graph(tenant_id)` per
operation. No connection is opened per operation.

Verified: `falkordb==1.8.0` installed. Its surface:

```
FalkorDB methods: close, config_get, config_set, from_url, list_graphs,
                  select_graph, udf_delete, udf_flush, udf_list, udf_load
select_graph(graph_id: str) -> falkordb.graph.Graph
list_graphs() → ['tenant_a', 'tenant_b', 'tenant_c']
```

`select_graph` is a cheap handle over the shared connection, which is exactly
the shape FR-055 and FR-021 both need. Isolation comes from the graph name, not
from a `WHERE` clause, as Constitution Principle I's technology note requires.

## R5. Tenant scale, measured

**Decision**: The scale proof creates 1,000 tenant graphs and reports the cost.
It is achievable, and the cost is higher than expected, so we publish it plainly.

Measured:

| Quantity | Value |
|---|---|
| Graphs created | 1,000, confirmed by `GRAPH.LIST` |
| Creation time | 2.94 s, sequential, 340 graphs/sec |
| Instance memory | 4.55 MB → 474.73 MB |
| Cost per tenant | about 459 KB of fixed overhead, holding one node each |
| Reclaimed on delete | 477.1 MB → 4.6 MB, so the cost is live, not leaked |
| Cross-tenant read | returned 0 rows, as required |

**One correction this forced.** `GRAPH.MEMORY USAGE` reports whole megabytes:

```
GRAPH.MEMORY USAGE probe_t0001 → total_graph_sz_mb: 0
```

A 459 KB graph therefore reads as `0 MB`. So per-tenant memory MUST come from
the `INFO memory` delta across a known number of graph creations.
`GRAPH.MEMORY USAGE` is still used, but for the component breakdown on one
larger graph, where it reports label matrices, relation matrices, node blocks,
attributes by label, and index size separately.

**The honest line for the README**: a graph per tenant is not free. It costs
roughly half a megabyte of fixed structure before any data. For 1,000 tenants
that is under 500 MB, which a laptop holds. For 100,000 tenants it would not be,
and we say so rather than implying the approach scales without limit.

## R6. Where the speed numbers come from

**Decision**: Never compute a percentile in Python. Read FalkorDB's own figures.

Verified instruments:

```
INFO latencystats
→ latency_percentiles_usec_graph.QUERY:p50=423.935,p99=7307.263,p99.9=7307.263

INFO commandstats
→ cmdstat_graph.QUERY:calls=5014,usec=...,usec_per_call=525.46,
   rejected_calls=0,failed_calls=0

Every GRAPH.QUERY reply
→ Query internal execution time: 0.253 milliseconds
   (Python client exposes it as result.run_time_ms)
```

**The overhead number falls straight out of this.** Measured on this machine:

| Side | Figure |
|---|---|
| Client, sequential indexed read | 972 ops/sec, so about 1,030 µs per operation |
| Server, same operations | 525 µs per call, from `commandstats` |
| **Auryn's own overhead** | **about 500 µs, roughly half the wall time** |

That is the number FR-042 asks us to publish, and it is also a finding: at one
connection, the client is the bottleneck, not FalkorDB. Which settles R7.

## R7. How the load generator must be built

**Decision**: Several worker processes, each with its own pooled connection.
Not threads, and not one process.

**Rationale**: R6 measured the single-process client ceiling at roughly 1,000
operations per second, while the server answered the same work in half the time.
A single-process benchmark would publish a number that understates FalkorDB by
about half. That would be a poor result to hand a FalkorDB judge.

Two server limits shape the design, both verified from `GRAPH.CONFIG GET *`:

```
THREAD_COUNT        2
OMP_THREAD_COUNT    2
MAX_QUEUED_QUERIES  25
TIMEOUT             1000
CACHE_SIZE          25
```

`MAX_QUEUED_QUERIES 25` is a hard ceiling. Past it FalkorDB refuses queries, and
`rejected_calls` in `commandstats` counts them. So the run reports succeeded,
refused and failed counts side by side, states the configuration it ran against,
and names what limited it. A sweep across thread counts gives an honest curve
rather than one convenient figure.

**Alternatives considered**: `asyncio` in one process. It removes waiting time
but not per-operation client cost, and it cannot use more than one core.
Rejected for the headline run, though it remains fine for the demo.

## R8. The model provider boundary

**Decision**: One small protocol with two implementations. `mock` is the
default. `gemini` activates only when `GEMINI_API_KEY` is present.

Verified about Gemini:

| Finding | Detail |
|---|---|
| Working model | `gemini-3.8-flash`, HTTP 200, confirmed three ways (header auth, query auth, with and without a generation config) |
| Retired model | `gemini-2.5-flash` returns HTTP 404: "no longer available to new users… use models/gemini-3.8-flash" |
| Thinking tokens | One short reply used `thoughtsTokenCount: 97`. A low output cap leaves no budget for visible text, so the reply comes back empty. Set a generous cap. |
| Transient failures | An early probe returned 404 for models that then worked on a clean retry. The provider needs one retry. |

**The switch must be invisible to the engine.** FR-025b requires that the engine
cannot tell which provider made a call. So the provider returns the same shape
in both cases: a reply and a list of requested memory operations. `mock` returns
scripted operations; `gemini` returns the ones the model chose through tool
calling.

## R9. The container runtime on this machine

**Decision**: Build locally against Rancher Desktop. Ship a `docker-compose.yml`
that a judge runs with plain Docker.

**Finding**: the Docker Desktop install on the build machine enforces an
organization sign-in and refuses every command. A second runtime (Rancher
Desktop) was already present, so local builds point `DOCKER_HOST` at its socket
instead.

**Second finding**: host port 6379 was already in use on the build machine. So
`docker-compose.yml` publishes `${AURYN_PORT:-6379}`. A judge gets 6379 by
default and never sees this.

Both are build-machine details and nothing more. No shared or managed
credential was used, and per Constitution Principle V none will be.

## R10. Why no eval framework

**Decision**: Write about 80 lines of measurement. Add no eval dependency.

**Rationale**: Recall correctness is deterministic. For each labelled request we
know the memories that should return, so precision, recall and rank are
arithmetic. DeepEval and LangWatch grade generated text with a judge model,
which costs credentials, varies between runs, and measures the language model
rather than Auryn. All three conflict with FR-038 and with Principle IV.

**Alternatives considered**: a single optional judge-model check, reporting
answer quality when a key is present. Allowed, but only after the video exists,
and it may never gate anything.

## Resolved unknowns

Every `NEEDS CLARIFICATION` marker in the specification is closed. Three were
answered by the author (FR-009, FR-016, FR-025) and recorded in the spec on
2026-10-18. The remaining open questions in this plan were technical, and all
ten were closed by probing the live container rather than by assumption.

## Risks that remain

| Risk | Likelihood | What we do about it |
|---|---|---|
| The 1,000-graph proof is slow on a judge's weaker machine | Medium | Make the tenant count a parameter, default lower, and state the figure we measured |
| `MAX_QUEUED_QUERIES 25` throttles the load run and reads as a weak result | Medium | Report `rejected_calls`, raise the limit deliberately, and publish both runs |
| Gemini returns a transient 404 during the video recording | Low | One retry in the provider, and the `mock` provider always works |
| Full-text index behaves differently than the probe suggested at volume | Low | The eval harness measures recall quality on 200 memories, which surfaces this |
| Time runs out | **High** | Principle VII. The eval harness is cut first, then the index before-and-after documentation |
