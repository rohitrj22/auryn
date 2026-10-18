# Implementation Plan: Auryn — Graph-Native Agent Memory

**Branch**: `001-agent-memory-engine` (spec directory; work proceeds on `main`) | **Date**: 2026-10-18 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-agent-memory-engine/spec.md`

## Summary

Auryn gives any AI agent memory that lives in a graph. One FalkorDB graph per
tenant holds three kinds of memory, the full history of every session, and the
record of work passed between agents. Recall follows links from the subjects a
request names, ranks by connection closeness and then recency, and does it in
one query. The engine carries no business vocabulary. A thin support-crew demo
sits on top and exists to prove the engine works.

Every claim the project makes is measured by FalkorDB's own instruments rather
than asserted by our code. Recall quality comes from a labelled fixture. Speed
comes from `INFO latencystats` and the per-query execution time FalkorDB
returns. Tenant scale comes from `GRAPH.LIST` and `INFO memory`.

## Technical Context

**Language/Version**: Python 3.14.5, managed with `uv`. Forced, not preferred:
`node` is absent on the build machine.

**Primary Dependencies**: `falkordb==1.8.0` (official client, verified
installed), `redis==8.1.0` (pulled in by it). `pytest` for tests. No web
framework. No agent framework. No eval framework.

**Storage**: FalkorDB 8.10.2 in a container. Verified running on host port 6399.
Modules loaded: `graph` ver 42201 and `vectorset` ver 1. It is the only store.
No second store exists, by Constitution Principle I.

**Testing**: `pytest` for unit and integration tests. Five standalone proof
scripts, one per Track 02 criterion, each printing a clear pass or fail. A
deterministic recall eval harness. A multi-process load generator.

**Target Platform**: A developer or judge machine, macOS or Linux, running a
container runtime. No hosted deployment required.

**Project Type**: A Python library with a command-line demo and a set of proof
scripts.

**Performance Goals**, taken from measurements on this machine, not guessed:

| Measured today | Figure | What it tells the plan |
|---|---|---|
| Sequential writes, one connection | 1,106 ops/sec | The client, not FalkorDB, is the ceiling here |
| Sequential indexed reads, one connection | 972 ops/sec | Same |
| FalkorDB server time per query | 525 µs average, 0.253 ms for a 5-row indexed read | FalkorDB has roughly twice the headroom the client uses |
| Auryn's own overhead | about 500 µs per operation, the gap between the two rows above | This is the number FR-042 asks us to publish |
| Tenant graph creation | 340 graphs/sec sequential | 1,000 tenants take 3 seconds to set up |

Goal: show that a single recall costs a small enough part of an agent's turn
that memory is never the slowest step. Goal for throughput: exceed the
single-connection figure above by generating load from several processes, and
report what then becomes the limit.

**Constraints**:

- FalkorDB defaults observed and verified: `THREAD_COUNT 2`, `OMP_THREAD_COUNT 2`,
  `MAX_QUEUED_QUERIES 25`, `TIMEOUT 1000`, `CACHE_SIZE 25`, `RESULTSET_SIZE 10000`.
  `MAX_QUEUED_QUERIES 25` is a hard concurrency ceiling by default. The load run
  must either stay inside it or raise it deliberately and say so.
- Deadline 2026-10-18 23:59 IST. Gates at 15:00, 18:00, 20:00, 21:00, 22:00, 23:00.
- Zero credentials must reach all five proofs (FR-026).
- The build machine's Docker install enforces an organization sign-in, so local
  builds point `DOCKER_HOST` at another runtime's socket. Host port 6379 was also
  taken, so compose publishes `${AURYN_PORT:-6379}`. Both are build-machine
  details only and MUST NOT appear in the README.

**Scale/Scope**: 1,000 tenant graphs, verified achievable. Measured cost:
470 MB for 1,000 graphs, about 459 KB per tenant of fixed overhead, fully
reclaimed on delete (477 MB back to 4.6 MB). Engine surface: four public
operations. Target size: engine about 800 lines, demo under 20% of source lines.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Gate | Status before Phase 0 |
|---|---|---|
| **I. Graph-Native Memory** (NON-NEGOTIABLE) | FalkorDB is the only store. Stopping it must break the product. | **PASS by design.** No cache, no file store, no in-memory fallback is planned. A proof script asserts the failure. |
| **II. Five Criteria Are the Deliverable** (NON-NEGOTIABLE) | Each of the five criteria has one judge-runnable command. | **PASS by design.** `proofs/p1` to `proofs/p5` map one-to-one. Nothing outside those five is planned before they pass. |
| **III. Domain-Agnostic Engine** | Engine contains no demo vocabulary. Demo under 20% of source lines. | **PASS by design.** `auryn/` holds only generic labels. A grep test enforces it. |
| **IV. Zero-Credential Runnability** | A clean clone with no key reaches all five proofs. | **PASS by design.** `mock` provider is the default. Gemini activates only when a key is present. |
| **V. Secrets and Data Hygiene** (NON-NEGOTIABLE) | No credential in repo or history. Synthetic data generated by committed code. | **PASS, already enforced.** `.env` is git-ignored and verified by `git check-ignore`. `demo/seed.py` will generate all data. |
| **VI. Submission Completeness** | All six rule-10 artifacts exist. | **IN PROGRESS.** Repo exists and is local-only. README, video and public push are scheduled at the 21:00 and 22:00 gates. |
| **VII. Ship The Demo** | Nothing built that does not serve a Principle II row. | **PASS by design.** Vectors, MCP exposure, a second demo and Track 01 entry are all deferred in the spec's Assumptions. |

**No violations to justify.** The Complexity Tracking section below is therefore
empty, as the template requires.

One Principle VII judgment is worth recording. The recall eval harness does not
map to a Track 02 criterion directly. It is in scope because it decides whether
the recall design chosen in FR-009 is good enough, replacing an opinion with a
measurement. If the 18:00 gate slips, the harness is the first thing cut.

## Project Structure

### Documentation (this feature)

```text
specs/001-agent-memory-engine/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── memory-api.md    # The engine's four public operations
│   ├── cypher.md        # Every query the product depends on
│   └── provider.md      # The model provider boundary
├── checklists/
│   └── requirements.md  # Spec quality checklist (all items pass)
└── tasks.md             # Phase 2 output, created by /speckit-tasks
```

### Source Code (repository root)

```text
auryn/                      # LAYER 1 — the product. No business vocabulary.
├── __init__.py             # Exports Memory and the three memory kinds
├── store.py                # One pooled connection; select_graph per tenant
├── schema.py               # Labels, range indexes, full-text indexes, bootstrap
├── queries.py              # EVERY Cypher string, parameterized, in one place
├── models.py               # Event, Fact, Procedure, Session, Turn, Task, Handoff
├── memory.py               # remember() recall() handoff() history()
├── consolidate.py          # The count rule that derives a Fact from Events
├── metrics.py              # Reads INFO latencystats, commandstats, GRAPH.MEMORY
└── providers/
    ├── __init__.py         # Provider protocol and the switch
    ├── mock.py             # Deterministic stand-in; scripted tool calls
    └── gemini.py           # gemini-3.8-flash; generous output cap

demo/                       # LAYER 2 — thin and replaceable. Target under 20%.
├── crew.py                 # Triage agent and Refund agent
├── seed.py                 # Synthetic support data, generated by code
└── run.py                  # Command-line entry for the demo

proofs/                     # One per Track 02 criterion. Each prints PASS or FAIL.
├── persistence.py       # Restart, empty prompt, still knows
├── memory_kinds.py      # Three kinds, recalled separately
├── handoff.py           # Agent B reads agent A's nodes, no message passed
├── isolation.py         # 1,000 tenant graphs; cross-tenant read returns nothing
├── concurrency.py       # Multi-process load; server-side percentiles
├── graph_required.py    # Principle I: stop FalkorDB, product must fail
├── bench/
│   ├── loadgen.py          # Several worker processes, each pooled
│   └── report.py           # Client vs server figures; rejected and failed counts
└── run_all.py              # Runs every proof; one exit code

# evals/ was planned and CUT. It was first in the cut order, and the time went
# to fixing recall's scaling instead. Recall quality is therefore described in
# words rather than measured. Stated here so the gap is recorded, not hidden.

tests/
├── unit/                   # Models, consolidation rule, metrics parsing
└── integration/            # Engine against a live FalkorDB

docker-compose.yml          # One service: falkordb. Judge runs this.
pyproject.toml              # uv-managed
.env.example                # Names the key; holds no value
README.md                   # Graph model, Cypher, measurements, setup, track
```

**Structure Decision**: A single Python project with a hard internal boundary.
`auryn/` is the product and imports nothing from `demo/`, `proofs/`, or `evals/`.
Everything else imports `auryn/`. This arrangement is what makes Principle III
testable: one grep over `auryn/` for demo vocabulary, and one import check.

Two choices inside that structure carry weight:

1. **Every Cypher string lives in `auryn/queries.py`.** Nothing else in the
   codebase writes Cypher. This makes FR-052 (always parameterized) a single-file
   audit, and it gives the README a single source for the published queries that
   rule 10 demands.
2. **`auryn/metrics.py` reads FalkorDB's instruments, and nothing else measures.**
   No component keeps its own counter. That is what stops us from publishing a
   number we computed about ourselves.

## Constitution Re-Check (after Phase 1 design)

| Principle | Verdict | Evidence in the design |
|---|---|---|
| **I. Graph-Native Memory** | **PASS** | `data-model.md` defines one graph per tenant and no second store. `proofs/graph_required.py` stops FalkorDB and asserts total failure. `contracts/memory-api.md` raises `StoreUnavailable` and forbids degrading. |
| **II. Five Criteria Are the Deliverable** | **PASS** | `quickstart.md` gives one command per criterion, each naming the requirements and success criteria it checks. |
| **III. Domain-Agnostic Engine** | **PASS** | Every label in `data-model.md` is generic. `tests/unit/test_layering.py` greps `auryn/` and checks imports. |
| **IV. Zero-Credential Runnability** | **PASS** | `contracts/provider.md` makes `mock` the default and deterministic. `quickstart.md` states "No API key" as a prerequisite. |
| **V. Secrets and Data Hygiene** | **PASS** | `.env` already git-ignored and verified. `demo/seed.py` generates all data. The Rancher Desktop detail is marked "not for the README" in `quickstart.md`. |
| **VI. Submission Completeness** | **ON TRACK** | `contracts/cypher.md` is the published query set rule 10 demands. README, video and public push remain scheduled. |
| **VII. Ship The Demo** | **PASS** | Vectors, MCP exposure, a second demo and Track 01 stay deferred. The cut order is written down: eval harness first, then index documentation. |

**Three design decisions that the research changed**, recorded so they are not
silently reversed later:

1. **Recall now starts with a full-text lookup**, not a subject-key match. The
   probe found FalkorDB ships a full-text index, which removes the weakness in
   the chosen option at no cost and no credential.
2. **Per-tenant memory is read from the `INFO memory` delta**, not from
   `GRAPH.MEMORY USAGE`. That command rounds to whole megabytes and reports a
   459 KB graph as `0 MB`.
3. **Full-text terms are joined with `|`.** A multi-word query means AND by
   default and would have returned nothing. This would have been a silent
   empty-recall bug.

## Layout decisions (recorded 2026-10-18 16:15 IST)

| Decision | Reason |
|---|---|
| Repository directory renamed `beacon` to `auryn` | The old name belonged to a different idea |
| Package stays `auryn/`, flat at the root | The package directory name **is** the import name. `from auryn import Memory` requires it. A `src/` package would force `from src import Memory`. |
| `src/auryn/` layout not adopted | It adds a level without reducing the repeated name, and costs packaging changes with hours left |
| `demo/providers/` holds every text generator | The engine references none of them. Enforced by `test_engine_needs_no_text_generator`. |
| `examples/` holds the integration example | A second domain, which evidences FR-035 |

## Complexity Tracking

> No Constitution Check violations, before or after design. This section is
> intentionally empty.
