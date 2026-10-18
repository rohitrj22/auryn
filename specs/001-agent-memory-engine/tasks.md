---
description: "Task list for Auryn — Graph-Native Agent Memory"
---

# Tasks: Auryn — Graph-Native Agent Memory

**Input**: Design documents from `/specs/001-agent-memory-engine/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md — all complete.

**Tests**: Test tasks appear only where the specification demands them. FR-028 requires one runnable check per Track 02 criterion, and FR-033 requires an enforced layering check. Wider test coverage is out of scope under Constitution Principle VII.

**Organization**: Grouped by user story, so each story is independently testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on unfinished work)
- **[Story]**: The user story this serves
- Every task names its exact file path

## Path Conventions

Single Python project at the repository root: `auryn/`, `demo/`, `proofs/`, `evals/`, `tests/`.

## Deadline and gates

Deadline **2026-10-18 23:59 IST**. Gates from the constitution:

| Gate | Time (IST) | Tasks that must be done |
|---|---|---|
| Engine reads and writes all three kinds | 15:00 | T001–T028 |
| Demo crew plus restart proof | 18:00 | T029–T035 |
| Benchmark and isolation proofs | 20:00 | T036–T045 |
| README complete | 21:00 | T050 |
| Video recorded | 22:00 | T053 |
| Submitted | 23:00 | T054 |

## Deferred decision (2026-10-18 14:35 IST)

The engine-to-demo split, the agent count, and the narrative order are **not
settled**. The engine is identical under every option, so the decision waits
until the engine runs. Phases 1, 2, 6 and 7 are unaffected. Phase 5 (the demo
crew) will be re-planned before it starts.

Two fixes are **in scope regardless**, because they are engine gaps rather than
demo choices: T014a subject resolution, and T014b `explain()`.

## Cut order, required by Constitution Principle VII

If a gate slips, cut in this order and no other. Record each cut in the README.

1. **First cut: the eval harness.** Phase 9, T046–T048. It measures a design choice rather than a judging criterion.
2. **Second cut: the index before-and-after documentation.** T049. The indexes still get built; only the published proof of their effect goes.
3. **Never cut**: any task in Phases 1 to 8, or T050 to T054. Those are the five criteria and the six required submission artifacts.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project skeleton and a verified container

- [x] T001 Create the source tree with an `__init__.py` in every package: `auryn/`, `auryn/providers/`, `demo/`, `proofs/`, `proofs/bench/`, `evals/`, `tests/`, `tests/unit/`, `tests/integration/`
- [x] T002 Write `docker-compose.yml` with one `falkordb` service from `falkordb/falkordb:latest`, publishing container port 6379 to host 6379, with a named volume for data
- [x] T003 [P] Write `pyproject.toml` requiring `python>=3.13`, with dependencies `falkordb==1.8.0` and `pytest`, and a `[project.scripts]` entry for the demo
- [x] T004 [P] Write `.env.example` containing only the line `GEMINI_API_KEY=` with no value, plus a comment pointing to `https://aistudio.google.com/apikey`
- [x] T005 [P] Extend `.gitignore` with `output/`, `.pytest_cache/`, and `*.egg-info/`. Confirm `.env` is still ignored by running `git check-ignore -v .env`
- [x] T006 Record the container's configuration baseline to `specs/001-agent-memory-engine/baseline-config.txt` by running `GRAPH.CONFIG GET *`, `MODULE LIST` and `INFO server`, so the benchmark can state what it ran against (FR-045)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The engine's shared parts. No user story can start until these exist.

**⚠️ CRITICAL**: Phase 3 onward depends on all of Phase 2.

- [x] T007 Create dataclasses in `auryn/models.py` for `MemoryRecord`, `Session`, `Turn`, `Task`, `Handoff`, `Stats`, `TaskContext`, and the constants `EPISODIC`, `SEMANTIC`, `PROCEDURAL`. Enforce these constraints verbatim from data-model.md: "A memory has exactly one kind of the three"; "`text` has a stated maximum length; truncation is recorded, never silent"; "`derived` is true only on a fact the engine concluded"; "Every memory records its writing agent"
- [x] T008 Implement `auryn/store.py` holding one `FalkorDB` client and calling `select_graph(tenant)` per operation, never opening a connection per operation (FR-055). Read the URL from `FALKORDB_URL`, default `falkor://localhost:6379`. Raise `StoreUnavailable` naming FalkorDB when unreachable, and never fall back to another store (FR-029). Raise `InvalidTenant` before any query when the tenant name is unsafe as a graph name
- [x] T009 Copy every query from `contracts/cypher.md` into `auryn/queries.py` as module constants. Pass all values as parameters, and never build a query by joining text (FR-052). Include the helper that splits a request into words and joins them with `|`, because a multi-word full-text query means AND by default and returns nothing otherwise
- [x] T010 Implement `auryn/schema.py` to bootstrap a tenant graph idempotently with five range indexes — `(:Subject) ON (key)`, `(:Memory) ON (at)`, `(:Memory) ON (id)`, `(:Session) ON (id)`, `(:Task) ON (id)` — and one full-text index via `CALL db.idx.fulltext.createNodeIndex('Memory','text')` (FR-050)
- [x] T011 Define the `Provider` protocol, plus `Reply` and `MemoryOp`, in `auryn/providers/__init__.py`, with a factory that picks `gemini` when `GEMINI_API_KEY` is set and `mock` otherwise, overridable by `AURYN_PROVIDER` (FR-027)
- [x] T012 [P] Implement `auryn/providers/mock.py` to return deterministic text and scripted `memory_ops`, with no network call, so the same input always gives the same output (FR-025a, FR-038)
- [x] T013 [P] Implement `auryn/providers/gemini.py` against `gemini-3.8-flash`. Set a generous `maxOutputTokens` because the model spends output budget on thinking and returns empty text under a tight cap. Retry once on failure. Never log the key. Raise `ProviderFailure` on empty text, distinguishable from an empty recall
- [x] T014 Implement `auryn/metrics.py` to read and return FalkorDB's own figures unchanged: `INFO latencystats` percentiles, `INFO commandstats` call, `rejected_calls` and `failed_calls` counts, `INFO memory`, `GRAPH.LIST`, and `GRAPH.CONFIG GET *`. Keep no counters of our own (FR-048)
- [x] T014a Add subject resolution to `auryn/schema.py` and `auryn/queries.py`: a full-text index on `(:Subject) ON (name)`, and a lookup that uses **AND** semantics, not OR. One match above threshold reuses that subject. Zero matches creates a new one. Several close matches create a new subject and link it `[:RELATED_TO]` to the nearest, so ambiguity never becomes a wrong merge (FR-057)
- [x] T014b Implement `explain(memory_id)` in `auryn/memory.py` returning the writing agent, the session, the events the memory was derived from, and the fact it superseded. One round trip (FR-011, FR-016a, FR-056)
- [x] T015 Export `Memory`, `EPISODIC`, `SEMANTIC`, `PROCEDURAL` and the error types from `auryn/__init__.py`
- [x] T016 Write `tests/unit/test_layering.py` to assert `auryn/` contains none of the words `ticket`, `refund`, `order`, `customer`, `support`, and imports nothing from `demo/`, `proofs/` or `evals/` (FR-033, FR-034, SC-010)

**Checkpoint**: The engine's foundation is ready. User stories can begin.

---

## Phase 3: User Story 1 — Memory that outlives the process (Priority: P1) 🎯 MVP

**Goal**: A user states a fact. The process restarts. With no conversation history supplied, the agent still knows.

**Independent Test**: Run `uv run python -m proofs.p1_persistence`. It states a fact in one process, exits, then starts a second process with an empty prompt and asserts the fact returns.

- [x] T017 [US1] Implement the `Memory` constructor in `auryn/memory.py` taking `tenant`, `url`, `provider`, `consolidate_after=3`, `recall_cap=20`, calling the schema bootstrap on first touch, plus `start_session(agent)` and `end_session(session)`
- [x] T018 [US1] Implement `remember()` in `auryn/memory.py` for the episodic kind, writing the node, linking its subjects, and attaching it to its session and writing agent. Use `MERGE` on `id` so a repeat write updates and never duplicates (FR-005)
- [x] T019a [US1] Implement `standing()` in `auryn/memory.py` returning every current fact and procedure with no query to match against, excluding superseded memories. Found necessary by the worked example in `examples/bring_your_own_agent.py`, where a dinner question missed a peanut allergy because no word was shared and no subject link existed
- [x] T019 [US1] Implement `recall()` in `auryn/memory.py` as one single round trip (FR-054), using the full-text lookup for starting nodes then the traversal, ranked by hops then recency then text score, capped at `recall_cap`, returning an empty list rather than an error when nothing matches (FR-009, FR-010)
- [x] T020 [US1] Implement `history()` in `auryn/memory.py` to return a session's turns in order, or to list the tenant's sessions newest first, readable after the writing process exits (FR-012 to FR-014)
- [ ] T021 [US1] Write `proofs/p1_persistence.py` to run a first session in a child process, let that process exit fully, then run a second child process that receives only a tenant id and asserts the stated fact comes back. Print `PASS` or `FAIL` and exit accordingly (SC-001)
- [ ] T022 [US1] Write `tests/integration/test_persistence.py` covering the three acceptance scenarios of User Story 1, including a brand-new tenant whose agent must not invent a past

**Checkpoint**: User Story 1 works alone. This is the minimum viable entry.

---

## Phase 4: User Story 2 — Three kinds, recalled by kind (Priority: P2)

**Goal**: What happened, what stays true, and how to do a task are stored and recalled separately.

**Independent Test**: Run `uv run python -m proofs.p2_memory_kinds`. Each kind is requested alone and returns only its own kind.

- [x] T023 [US2] Extend `remember()` in `auryn/memory.py` to the semantic and procedural kinds, writing both labels so every memory carries the generic `Memory` label and its kind, and storing `trigger` on a procedure
- [x] T024 [US2] Add the `kind` filter to `recall()` in `auryn/memory.py` using `$kind IN labels(m)`, returning all kinds when `kind` is `None` (FR-006, FR-007)
- [x] T025 [US2] Implement supersession in `auryn/memory.py`: a new fact about the same subject marks the earlier fact `superseded` and links `[:SUPERSEDES]`, keeping the older fact readable rather than deleting it (FR-004)
- [x] T026 [US2] Implement the count rule in `auryn/consolidate.py`: when events about one subject reach `consolidate_after`, write a fact with `derived: true` and link `[:DERIVED_FROM]` to every contributing event. Use counting only, with no model involved (FR-016, FR-016a, FR-016b, FR-016c)
- [ ] T027 [US2] Write `proofs/p2_memory_kinds.py` asserting each kind returns alone, that a contradicted fact is flagged and kept, and that a derived fact links back to its events. Print `PASS` or `FAIL` (SC-002)
- [ ] T028 [US2] Write `tests/unit/test_consolidate.py` for the count rule at, below and above the threshold, and `tests/integration/test_kinds.py` for the five acceptance scenarios of User Story 2

**Checkpoint**: 15:00 gate. The engine reads and writes all three kinds in FalkorDB.

---

## Phase 5: User Story 3 — One agent picks up another's work (Priority: P3)

**Goal**: A second agent continues a task from shared state alone, with no message passed to it.

**Independent Test**: Run `uv run python -m proofs.p3_handoff`. The second agent runs in a separate process with only a tenant and a task id.

- [x] T029 [US3] Implement `handoff()` in `auryn/memory.py` recording the passing agent, the receiving agent, the task and the time, and moving the `[:OWNS]` edge to the new owner (FR-017)
- [x] T030 [US3] Implement `pick_up()` in `auryn/memory.py` returning every memory, subject and prior owner connected to a task, from a tenant and task id alone, in one round trip (FR-018, FR-054). Also implement the open-task listing with its owner (FR-020)
- [x] T030a [US3] Fix the data-loss bug in supersession in `auryn/queries.py` and `auryn/memory.py`. Supersession is now explicit via `remember(..., supersedes=...)`. Inferring it from a shared subject buried a second allergy, and under eight parallel writes it left zero memories standing (FR-004, FR-064)
- [x] T030b [US3] Add shared-state primitives to `auryn/queries.py` and `auryn/memory.py`: `join()`, `leave()`, `add_part()`, `claim()`, `release()`, `unclaimed_parts()`, `in_flight()`, `parts_status()`. A swarm joins additively; handoff still moves a single owner (FR-058 to FR-063)
- [x] T030c [US3] Prove `claim()` is atomic with real process contention, not by assumption. Measured: 16 processes, 25 rounds, exactly one winner every round (FR-060, SC-021)
- [ ] T031 [US3] Write `demo/seed.py` to generate synthetic support data in code, with a fixed seed so a judge can reproduce it. Use no real or scraped data (FR-031)
- [ ] T032 [US3] Write `demo/crew.py` with a Triage agent and a Refund agent. Each calls the engine through the provider's `memory_ops`, so the model decides what to remember when a key is present and scripted calls stand in otherwise (FR-025). Keep the file thin; the demo must stay under 20% of source lines
- [ ] T033 [US3] Write `demo/run.py` as the command-line entry, accepting a tenant and an optional task, and printing the conversation
- [ ] T034 [US3] Write `proofs/p3_handoff.py` running the Triage agent to completion in one process, then the Refund agent in a **separate** process given only a tenant and a task id. Assert the second agent states the first agent's facts, and assert no message object passed between them (FR-019, SC-003)
- [ ] T035 [US3] Write `tests/integration/test_handoff.py` for the four acceptance scenarios of User Story 3, including a task handed to an agent that never runs, which must stay open with a named owner

**Checkpoint**: 18:00 gate. The demo crew runs and the restart proof passes.

---

## Phase 6: User Story 4 — One tenant's memory never reaches another (Priority: P4)

**Goal**: Isolation is the graph boundary, proved at scale, measured by FalkorDB.

**Independent Test**: Run `uv run python -m proofs.p4_isolation --tenants 1000`.

- [ ] T036 [US4] Write `proofs/p4_isolation.py` accepting `--tenants` with a default of 1000, creating that many tenant graphs through the engine, and counting them with `GRAPH.LIST` rather than a count we kept (FR-048)
- [ ] T037 [US4] Add per-tenant memory measurement to `proofs/p4_isolation.py` from the `INFO memory` delta across a known number of creations. Do **not** use `GRAPH.MEMORY USAGE` for this, because it rounds to whole megabytes and reports a 459 KB graph as `0 MB`. Use `GRAPH.MEMORY USAGE` only for the component breakdown on one larger graph (FR-049)
- [ ] T038 [US4] Add cross-tenant read attempts to `proofs/p4_isolation.py` across at least 1,000 attempts spanning at least 10 tenants, asserting zero rows return every time, plus a new tenant that works with no prior setup and a named tenant that does not exist returning nothing without error (FR-022, FR-023, SC-004)

---

## Phase 7: User Story 5 — Memory keeps up under concurrent load (Priority: P5)

**Goal**: Publish honest, measured throughput and delay, naming the limit.

**Independent Test**: Run `uv run python -m proofs.p5_concurrency --procs 8 --seconds 30`.

- [ ] T039 [US5] Write `proofs/bench/loadgen.py` generating mixed reads and writes across many tenants from several worker **processes**, each with its own pooled connection, so the single-process client ceiling is never what gets measured (FR-046). Measured baseline to beat: 1,106 writes/sec and 972 indexed reads/sec on one connection
- [ ] T040 [US5] Write `proofs/bench/report.py` printing client throughput and delay beside FalkorDB's own `p50`, `p99` and `p99.9` from `INFO latencystats`, plus `rejected_calls` and `failed_calls`, plus the configuration the run used, plus Auryn's own overhead stated as the client-minus-server gap (FR-041 to FR-045, SC-015)
- [ ] T041 [US5] Write `proofs/p5_concurrency.py` to run the load, assert zero lost writes and zero cross-tenant reads, and require the report to name what limited the run. Refuse to print a figure with no named cause (FR-047, SC-016)
- [ ] T042 [US5] Add a sweep over `THREAD_COUNT` and `MAX_QUEUED_QUERIES` to `proofs/p5_concurrency.py`, since the observed defaults are 2 and 25 and the queue limit is a hard ceiling. Report the curve, and report `rejected_calls` at each point rather than hiding the refusals

**Checkpoint**: 20:00 gate. Benchmark and isolation proofs pass.

---

## Phase 8: User Story 6 — A judge runs every proof with no credentials (Priority: P6)

**Goal**: A clean clone with no key reaches five passing proofs in under ten minutes.

**Independent Test**: Clone into an empty directory with no `.env` and follow the README.

- [ ] T043 [US6] Write `proofs/p0_graph_required.py` for Constitution Principle I: with FalkorDB stopped, every proof must fail and each must name FalkorDB as unavailable. The proof fails if anything still answers, because that would mean a second store exists (FR-029, SC-009)
- [ ] T044 [US6] Write `proofs/run_all.py` to run every proof in order, print one line per criterion, and return a single exit code (FR-028)
- [ ] T045 [US6] Rehearse a clean clone: copy the repository to a fresh directory with no `.env`, run only the README steps, and time it. Fix whatever blocks a judge. Target under ten minutes (SC-008)

---

## Phase 9: Recall quality measurement — **FIRST TO CUT**

**Purpose**: Replace an opinion about recall ranking with a measurement.

**Cut rule**: If the 18:00 gate slips, drop this whole phase and note it in the README.

- [ ] T046 Write `evals/fixture.py` generating about 200 memories across 20 tenants and about 40 labelled requests, each naming the memories that ought to return. Generate it in code with a fixed seed so a judge can rebuild it (FR-040)
- [ ] T047 [P] Write `evals/metrics.py` computing precision@k, recall@k and mean reciprocal rank. Arithmetic only, with no model involved (FR-037)
- [ ] T048 Write `evals/run_eval.py` to print a results table and exit non-zero below a stated threshold, running offline with no credentials and giving an identical result on two consecutive runs (FR-038, FR-039, SC-013, SC-014)

---

## Phase 10: Polish, Submission and Cross-Cutting Concerns

- [ ] T049 **SECOND TO CUT.** Write `proofs/bench/profile_report.py` printing the recall query's `GRAPH.PROFILE` plan before and after indexing, with both timings and the `Cached execution` flag proving plan reuse. Save the output for the README (FR-051, FR-053, SC-019, SC-020)
- [ ] T050 Write `README.md` containing: the named track; setup steps that work with no credentials; the graph data model from data-model.md; every Cypher query from contracts/cypher.md; the measured numbers including per-tenant memory cost and Auryn's own overhead; a 20-line second-domain example evidencing the engine is generic (FR-035); the disclosure that an AI coding assistant was used; and every cut recorded. State the per-tenant cost plainly rather than implying the design scales without limit
- [ ] T051 Scan the whole repository and its full git history for credential patterns, and confirm `git check-ignore -v .env` still reports it ignored. Any hit blocks the submission (FR-032, SC-012)
- [ ] T052 Create the public repository, push `main`, and confirm from a logged-out view that `.env` is absent and the README renders
- [ ] T053 Record the demo video to `output/demo.mp4` and link it from `README.md`. Show the restart proof, the handoff across two processes, the isolation proof at scale, and the benchmark report. Use a real Gemini key so the model's own decisions are visible. Never show the key on screen
- [ ] T054 Submit on WeMakeDevs before 23:00 IST, naming Track 02 and attaching the repository, the video and the setup steps, leaving one hour of buffer

---

## Dependencies

**Phase order**: Phase 1 → Phase 2 → Phases 3 to 8 in order → Phase 9 → Phase 10.

**Story dependencies**:

| Story | Depends on | Why |
|---|---|---|
| US1 (P1) | Phase 2 only | The MVP. Nothing else blocks it. |
| US2 (P2) | Phase 2, and T018–T019 from US1 | Extends `remember()` and `recall()` |
| US3 (P3) | US2 | The crew writes all three kinds |
| US4 (P4) | Phase 2 only | Independent of US1 to US3. Could run earlier if a gate slips. |
| US5 (P5) | Phase 2, plus T019 | Needs a real recall query to load |
| US6 (P6) | US1 to US5 | It packages them, so it has nothing to package before they exist |

**Hard blockers**: T008 blocks everything. T009 blocks T010, T018, T019. T011 blocks T012, T013, T032.

## Parallel execution examples

**Phase 1**: T003, T004, T005 touch different files and can run together.

**Phase 2**: T012 and T013 are two separate provider files and run together. T016 touches only a test file and can run at any time after T001.

**Phase 9**: T047 is pure arithmetic in its own file and does not wait for T046.

**Across stories after Phase 2**: US4's tasks (T036 to T038) touch only `proofs/p4_isolation.py` and depend on nothing from US1 to US3. They can proceed beside Phase 3 work if the schedule tightens.

## Implementation strategy

**MVP first.** Phase 1, Phase 2, Phase 3. That alone is a viable Track 02 entry, because memory surviving a restart is the claim the whole product rests on.

**Then increments, each independently demonstrable**: add US2 for the three kinds, then US3 for coordination, then US4 and US5 for the measured claims, then US6 to package it for a judge.

**Under time pressure**, apply the cut order above and nothing else. Phases 1 to 8 and T050 to T054 are the five judging criteria and the six required artifacts. Cutting any of those loses the entry rather than shrinking it.
