# Feature Specification: Auryn — Graph-Native Agent Memory

**Feature Branch**: `001-agent-memory-engine` (spec directory; no feature branch created, work proceeds on `main`)

**Created**: 2026-10-18

**Status**: Ready for planning — all clarifications resolved 2026-10-18

**Input**: User description: "Auryn — a graph-native memory engine for AI agents, built on FalkorDB. Submission for Track 02 (Agent Memory and Coordination) of the WeMakeDevs Graph Hacks hackathon. Two layers: a domain-agnostic memory engine, and a thin support-crew demo. The five Track 02 judging criteria are the deliverable, and each needs a command a judge can run."

## Who This Serves

Three actors use this product, and each one judges it differently.

| Actor | What they want | How they measure it |
|---|---|---|
| **Agent developer** | Give an agent memory without designing a memory system | Lines of code to add memory to an existing agent |
| **End user (tenant)** | An agent that remembers them, and that never leaks their data to another user | The agent recalls a fact from a past session; no stranger's data appears |
| **Hackathon judge** | Verify the five Track 02 criteria quickly, on their own machine | One command per criterion, each printing a clear pass or fail |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Memory that outlives the process (Priority: P1)

An end user talks to an agent and states something about themselves. Days later
they return. The process has restarted. No conversation history is supplied to
the agent. The agent still knows what they said, and refers to it without being
asked.

**Why this priority**: This is the single claim the whole product rests on, and
it is the one a judge grasps in ten seconds. If only this ships, the entry is
viable. Every other story adds to it rather than enabling it.

**Independent Test**: Run a first session and state a fact. Stop the process.
Start a second session with an empty prompt. Confirm the agent states the fact
back. Delivers the core value of the product on its own.

**Acceptance Scenarios**:

1. **Given** a tenant with no memory, **When** the user says "my order 441 arrived damaged" and the session ends, **Then** the statement is stored as something that happened, with the time it happened.
2. **Given** a stored memory and a fully restarted process, **When** a new session starts with no conversation history supplied, **Then** the agent's first reply refers to order 441 without the user mentioning it.
3. **Given** a tenant with no memory at all, **When** a new session starts, **Then** the agent opens normally and does not invent a past.

---

### User Story 2 - Three kinds of memory, recalled by kind (Priority: P2)

A developer stores three different kinds of knowledge about a user, and asks
for them back separately. What happened is kept apart from what stays true, and
both are kept apart from how to carry out a task.

**Why this priority**: Track 02 names these three kinds explicitly. A single
undifferentiated note store does not satisfy the criterion. It also raises
answer quality, because a rule is not a past event.

**Independent Test**: Store one memory of each kind. Ask for each kind
separately and confirm each request returns only its own kind. Ask without
naming a kind and confirm all three can be returned.

**Acceptance Scenarios**:

1. **Given** an empty tenant, **When** the developer stores "the user asked for a refund on 2 October", **Then** it is retrievable as something that happened, carrying its time.
2. **Given** an empty tenant, **When** the developer stores "the user prefers email over phone", **Then** it is retrievable as a fact that stays true, with no time attached as a condition of its truth.
3. **Given** an empty tenant, **When** the developer stores "a refund above 500 needs manager approval", **Then** it is retrievable as a task procedure.
4. **Given** all three kinds stored, **When** the developer asks only for facts that stay true, **Then** no past events and no procedures are returned.
5. **Given** a fact that is later contradicted, **When** the newer fact is stored, **Then** the older fact is marked superseded rather than deleted, and the current answer uses the newer one.

---

### User Story 3 - One agent picks up another agent's work (Priority: P3)

A first agent handles the start of a task and records what it learned. A second
agent, running later and separately, continues the task. The second agent
receives no summary and no transcript from the first. It reads shared state and
continues correctly.

**Why this priority**: This is the "coordination" half of the track name.
Handoff through shared state, rather than through a long passed message, is the
point a graph makes better than a chat log.

**Independent Test**: Run the first agent to completion. Start the second agent
in a separate process with only a tenant identifier and a task identifier.
Confirm it states the facts the first agent gathered and takes the correct next
step.

**Acceptance Scenarios**:

1. **Given** the first agent has gathered facts for a task, **When** it hands the task off, **Then** the handoff records who passed it, who receives it, the task, and the time.
2. **Given** a handed-off task, **When** the second agent starts in a separate process with no transcript, **Then** it can state the facts the first agent gathered.
3. **Given** a handed-off task, **When** the second agent completes it, **Then** the outcome is readable by the first agent on its next run.
4. **Given** a task handed to an agent that never runs, **When** a third party inspects the task, **Then** the task shows as open with a named owner, not as lost.

---

### User Story 4 - One tenant's memory never reaches another (Priority: P4)

Two end users talk to the same agent about similar topics. Neither user's
memory ever appears in the other's conversation, and no request can retrieve
across the boundary.

**Why this priority**: Track 02 names per-user separation. It is also the
difference between a demo and something a company could use. A leak here
invalidates the product regardless of the other stories.

**Independent Test**: Store a distinctive memory for tenant A. Ask for it as
tenant B. Confirm nothing is returned. Confirm the same request as tenant A
returns it.

**Acceptance Scenarios**:

1. **Given** tenant A has stored a distinctive fact, **When** tenant B asks for anything, **Then** tenant A's fact is never returned.
2. **Given** tenant B is a new tenant, **When** tenant B's first session starts, **Then** tenant B's memory is empty and no setup step is required beforehand.
3. **Given** a request that names a tenant that does not exist, **When** the request runs, **Then** it returns nothing and reports no error about a missing tenant.
4. **Given** one tenant's memory is removed entirely, **When** another tenant reads memory, **Then** that other tenant is unaffected.

---

### User Story 5 - Memory keeps up under concurrent load (Priority: P5)

Many agents read and write memory at the same time, for many tenants. Memory
stays correct and fast enough to sit inside an agent's loop rather than beside
it.

**Why this priority**: Track 02 names high-concurrency reads and writes. A
measured number is also the only claim in the entry that a judge cannot argue
with. It ranks below correctness because a fast wrong answer scores nothing.

**Independent Test**: Run a load generator that mixes reads and writes across
many tenants at once. Confirm it reports throughput and delay figures, and
confirm every write is readable afterwards.

**Acceptance Scenarios**:

1. **Given** a load run across many tenants at once, **When** the run finishes, **Then** it reports operations per second and the delay at the median and at the 95th percentile.
2. **Given** a load run that mixes reads and writes, **When** the run finishes, **Then** no write is lost and no read returns another tenant's data.
3. **Given** a load run, **When** the run finishes, **Then** it reports zero errors, or it names every error it saw.

---

### User Story 6 - A judge runs every proof with no credentials (Priority: P6)

A judge clones the repository on a machine with no API keys. They follow the
setup steps and run each of the five proofs. Everything works, and nothing asks
them to sign up for anything.

**Why this priority**: A proof a judge cannot run scores nothing. This story
protects the value of all five stories above it, which is why it exists, and it
sits last only because it has nothing to package until they exist.

**Independent Test**: Clone into a clean directory with no stored credentials.
Follow the written steps. Confirm all five proofs run and report pass.

**Acceptance Scenarios**:

1. **Given** a clean clone and no credentials, **When** the judge follows the setup steps, **Then** all five proofs run and report a result.
2. **Given** a credential is supplied later, **When** the judge re-runs the demo, **Then** the agent's replies are generated by a real language model, and no other behaviour changes.
3. **Given** the graph database is stopped, **When** any proof runs, **Then** it fails with a clear message naming the stopped database. It MUST NOT answer from a second store.

---

### Edge Cases

- **A fact contradicts an older fact.** The newer fact wins for answering, and the older one is kept and marked superseded, so the change is traceable.
- **Recall finds nothing.** The agent says it has no memory of the topic. It MUST NOT invent one.
- **Recall finds too much.** The amount returned is capped, and the cap is stated, so an agent's input never grows without limit.
- **The same memory is stored twice.** The second store does not create a duplicate that would double-count in recall.
- **A session ends without a clean close**, for example the process is killed. Memory written before that moment survives and stays readable.
- **Two agents write to the same task at the same time.** Both writes survive, and the task's state stays readable and consistent.
- **A tenant identifier contains unexpected characters.** It is rejected or made safe, and it can never reach another tenant's memory.
- **The graph database is unreachable at startup.** The product reports this plainly and stops. It MUST NOT start with memory silently disabled.
- **The language model returns empty text.** The turn reports a model failure. Memory already written is not rolled back, and the failure is distinguishable from "no memory found".
- **A very long user statement arrives.** It is stored without truncating it silently, or the truncation is recorded.

## Requirements *(mandatory)*

### Functional Requirements

**Storing memory**

- **FR-001**: The engine MUST store a memory as one of exactly three kinds: something that happened, a fact that stays true, or a procedure for a task.
- **FR-002**: The engine MUST record, for every memory, the tenant it belongs to, the session it arose in, the agent that wrote it, and the time it was written.
- **FR-003**: The engine MUST let a memory be linked to the subjects it concerns, so related memories can be reached from each other.
- **FR-004**: The engine MUST mark an older memory as out of date **only when the caller names it explicitly**, and MUST keep it readable. The engine MUST NOT infer this from a shared subject, because two different facts about one subject are both true, and because inference destroys concurrent writes.
- **FR-005**: The engine MUST NOT create a duplicate when the same memory is stored a second time.

**Recalling memory**

- **FR-006**: Users of the engine MUST be able to ask for memories of one named kind only.
- **FR-007**: Users of the engine MUST be able to ask for memories without naming a kind, and receive all kinds.
- **FR-008**: The engine MUST cap how much any single recall returns, and MUST state that cap.
- **FR-009**: The engine MUST rank recalled memories by closeness of connection first, and by recency second. Closeness means the number of links between the request's subjects and the memory. The engine MUST resolve the subjects named in a request, follow their links out to a stated maximum distance, and MUST do so in one single request to the store.
- **FR-009a**: The engine MUST NOT rank by meaning-based similarity in this version. Numeric fingerprints of memories are out of scope here. The eval harness of FR-036 exists so this choice can be revisited with measurements rather than opinion.
- **FR-010**: The engine MUST return an empty result, not an error, when nothing matches.
- **FR-011**: The engine MUST be able to report, for any recalled memory, the session and the agent that wrote it, so an answer can be traced to its origin.

**Conversation history**

- **FR-012**: The engine MUST store every turn of a conversation, in order, against its session.
- **FR-013**: The engine MUST keep a session readable after the process that created it has exited.
- **FR-014**: Users of the engine MUST be able to list a tenant's past sessions, and read any one of them.
- **FR-015**: An agent MUST be able to start a new session and recall from past sessions without any conversation history being supplied to it.

**Consolidation**

- **FR-016**: The engine MUST derive a lasting fact by itself when the same subject appears in a stated number of separate events. The rule MUST be a count, so it never depends on a language model.
- **FR-016a**: A derived fact MUST stay linked to every event it came from, so a reader can see why the engine concluded it.
- **FR-016b**: A derived fact MUST be marked as derived, so it is distinguishable from a fact a user stated directly.
- **FR-016c**: The count that triggers derivation MUST be adjustable by the calling application, and MUST have a stated default.

**Coordination between agents**

- **FR-017**: The engine MUST let one agent hand a task to another, recording who passed it, who receives it, the task, and the time.
- **FR-018**: A receiving agent MUST be able to read everything the passing agent recorded, using only a tenant identifier and a task identifier.
- **FR-019**: No summary, transcript, or message may pass directly between the two agents. Shared state MUST be the only channel.
- **FR-020**: Users of the engine MUST be able to list open tasks and name the agent that owns each one.

**Many agents working at once (shared state)**

- **FR-058**: Any number of agents MUST be able to work one task at the same time. Adding an agent MUST NOT remove another.
- **FR-059**: A task MUST be divisible into parts, so work can spread across agents.
- **FR-060**: When several agents compete for one part, exactly one MUST win. The rest MUST learn it is taken and move on.
- **FR-061**: An agent MUST be able to read what the other agents have written while they are still working.
- **FR-062**: Users of the engine MUST be able to see which agents are working on what, at any moment.
- **FR-063**: Progress across every part of a task MUST be readable in one request.
- **FR-064**: Concurrent writes MUST NOT destroy each other. A memory MUST be marked out of date only when the caller says so explicitly, never because it shares a subject with a newer one.

**Separation between tenants**

- **FR-021**: Each tenant's memory MUST live in its own isolated store, not in a shared store separated by a filter in a request.
- **FR-022**: No request made on behalf of one tenant may return another tenant's memory, under any input.
- **FR-023**: A new tenant MUST work with no setup step performed in advance.
- **FR-024**: Removing one tenant's memory MUST leave every other tenant unaffected.

**Who decides what to remember**

- **FR-025**: When a real language model is in use, the model MUST decide what is worth remembering, by calling the engine as one of the tools available to it.
- **FR-025a**: When the stand-in text generator is in use, fixed scripted calls MUST stand in for those decisions.
- **FR-025b**: The engine MUST behave identically in both cases, and MUST NOT be able to tell which one made the call.
- **FR-025c**: Every stored memory MUST record which agent wrote it, so the origin of a decision is always readable.

**Running and proving it**

- **FR-026**: The product MUST run end to end with no credentials supplied, using a stand-in text generator.
- **FR-027**: The product MUST switch to a real language model when a credential is present, with no change to any other behaviour and no code change.
- **FR-028**: The product MUST provide one runnable command per Track 02 criterion, and each MUST print a clear pass or fail.
- **FR-029**: The product MUST fail, with a message naming the stopped graph database, when that database is unavailable. It MUST NOT answer from any other store.
- **FR-030**: The product MUST report measured throughput and delay figures from a concurrent load run, rather than claimed figures.
- **FR-031**: All demonstration data MUST be synthetic and MUST be produced by code included in the repository, so a judge can reproduce it.
- **FR-032**: No credential may appear in the repository, its history, its documentation, or the demonstration video.

**Measuring recall quality**

- **FR-036**: The product MUST include a labelled set of memories and requests, where each request names the memories that ought to come back.
- **FR-037**: The product MUST report, against that labelled set, how much of what came back was correct, how much of what should have come back did, and how highly the best correct answer ranked.
- **FR-038**: That measurement MUST run with no credentials, and MUST give the same result every run.
- **FR-039**: The measurement MUST fail the build when quality drops below a stated threshold.
- **FR-040**: The labelled set MUST be produced by code in the repository, so a judge can rebuild it.

**Measuring speed and scale honestly**

- **FR-041**: Every speed figure MUST be reported twice: once as the caller experiences it, and once as the store itself reports it.
- **FR-042**: The product MUST report the gap between those two figures as its own overhead, rather than describing it in words.
- **FR-043**: Spread figures, at the middle and at the upper end, MUST come from the store's own measurements, not from the caller's arithmetic.
- **FR-044**: A load run MUST report how many requests the store refused and how many failed, alongside how many succeeded.
- **FR-045**: A load run MUST state the store's configuration it ran against, including thread counts and the queue limit.
- **FR-046**: A load run MUST generate its load from several separate processes, so the caller's own limits are never what gets measured.
- **FR-047**: A load run MUST name what limited it. An unexplained figure MUST NOT be published.
- **FR-048**: The tenant-scale proof MUST count tenant stores using the store's own listing command, not a count the product kept itself.
- **FR-049**: The tenant-scale proof MUST report memory used per tenant, and memory used by the whole instance, from the store's own reporting.

**Proving the speed work was done**

- **FR-050**: Every field that recall filters on MUST be indexed.
- **FR-051**: The documentation MUST show the recall request's execution plan before and after indexing, with both timings, taken from the store's own plan output.
- **FR-052**: Every request to the store MUST pass values as parameters. A request MUST NOT be assembled by joining text.
- **FR-053**: The documentation MUST show that repeated requests reuse a cached plan, using the store's own reporting of that fact.
- **FR-054**: A single recall MUST cost one request to the store. A pattern that fetches records and then fetches their neighbours separately MUST NOT be used.
- **FR-055**: Connections to the store MUST be pooled and reused. A connection MUST NOT be opened per operation.

**Keeping the engine reusable**

- **FR-033**: The engine MUST contain no vocabulary from the demonstration's subject area, so it can serve another subject area unchanged.
- **FR-034**: The demonstration MUST depend on the engine, and the engine MUST NOT depend on the demonstration.
- **FR-035**: The documentation MUST show the engine serving a second, different subject area, to evidence FR-033.

### Key Entities

- **Tenant**: One end user or one customer organisation. Owns an isolated body of memory. Nothing crosses between tenants.
- **Session**: One continuous conversation, belonging to a tenant. Has a start time, an end time, and an ordered list of turns. Outlives the process that created it.
- **Turn**: One utterance within a session, by the user or by an agent, with its position in order.
- **Event**: Something that happened, with the time it happened. The record of experience.
- **Fact**: Something held to stay true, with no time limit as a condition of its truth. May supersede an earlier fact.
- **Procedure**: How to carry out a task, including any conditions and thresholds it depends on.
- **Agent**: A named participant that reads and writes memory. Writes carry the name of their author.
- **Task**: A unit of work that may outlive one session and may move between agents. Has a state and a current owner.
- **Handoff**: The record of a task moving from one agent to another, with both names and the time.
- **Subject**: Anything a memory is about, which lets related memories be reached from one another.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user's stated fact is recalled correctly in a later session, after the process has fully restarted, with no conversation history supplied. Measured across at least five stated facts, with five of five recalled.
- **SC-002**: Each of the three memory kinds can be requested alone, and each request returns only its own kind, in ten of ten attempts.
- **SC-003**: A second agent continues a handed-off task correctly, using only a tenant identifier and a task identifier, in ten of ten attempts. No message passes between the agents in any attempt.
- **SC-004**: Across at least one thousand attempts spanning at least ten tenants, zero memories cross a tenant boundary.
- **SC-005**: A concurrent load run reports its measured throughput and its delay at the median and the 95th percentile, and loses zero writes.
- **SC-006**: A typical recall returns within the time an agent can afford inside its own loop, so memory does not become the slowest step of a turn.
- **SC-007**: An agent developer adds memory to an existing agent in ten lines of code or fewer, counted from the documented example.
- **SC-008**: A judge starting from a clean copy, with no credentials, reaches all five passing proofs in under ten minutes, following the written steps only.
- **SC-009**: With the graph database stopped, every proof fails and names the stopped database. No proof answers from memory.
- **SC-010**: A search of the engine for the demonstration's subject-area words returns zero results.
- **SC-011**: Every artifact the hackathon requires exists before the deadline: a public repository, written setup steps, the published data model, the published requests the product depends on, a demonstration video, and the named track.
- **SC-012**: A search of the whole repository history for credential patterns returns zero results.

- **SC-013**: Against the labelled set, the share of correct results among the top five is reported, and the share of expected results found in the top five is reported. Both are published as numbers, not adjectives.
- **SC-014**: The quality measurement produces an identical result on two consecutive runs, with no credentials present.
- **SC-015**: Auryn's own overhead, measured as the gap between caller-side and store-side timing of the same operation, is published as a number.
- **SC-016**: The load run publishes refused and failed request counts, the configuration it ran against, and a named cause for whatever limited it.
- **SC-017**: The tenant count in the scale proof comes from the store's own listing command, and is at least one thousand separate tenant stores.
- **SC-018**: Memory per tenant and total instance memory are published, both read from the store's own reporting.
- **SC-019**: The recall request's execution plan is published for both the unindexed and the indexed case, showing the scan type changed and the timing improved.
- **SC-020**: A reader can confirm from the store's own output that repeated recall requests reuse a cached plan.

- **SC-021**: With sixteen agents competing for one piece of work across twenty-five rounds, exactly one wins every round. Measured: 25 of 25.
- **SC-022**: With eight agents working one job split into ten parts, every part completes exactly once, with zero duplicates, and every finding is readable by every agent.

## Assumptions

These are decisions taken where the description left room, and constraints
inherited from the hackathon and from the machine this is built on.

**Inherited constraints, not choices**

- The graph database is FalkorDB, and the hackathon requires it to do the real work. Stopping it must break the product. This is rule 2 and rule 3 of the hackathon.
- The deadline is 2026-10-18 at 23:59 IST and does not move.
- The implementation language is Python, because `node` is not installed on the build machine.
- The graph database runs in a container locally. A hosted deployment is preferred by the rules but is not required when setup steps are complete.

**Assumed defaults**

- One isolated store per tenant is achievable in the chosen graph database without running a separate deployment for each tenant. The product relies on this.
- A stand-in text generator is sufficient to exercise every memory path, because the engine never depends on what the generated text says.
- Memory is kept for the life of the demonstration. No retention or expiry policy ships, because the hackathon demonstrates days, not years.
- The demonstration subject area is customer support, chosen because memory across weeks is self-evident there and needs no explanation to a judge.
- Memory is stored as written text, with a stated limit on length. Images, audio, and files are out of scope.
- Authentication is out of scope. The tenant identifier is supplied by the calling application, which is assumed to have already established who the user is.
- Deleting or correcting memory on an end user's request is out of scope beyond removing a whole tenant, which FR-024 covers.
- The concurrency figure is whatever the run measures on the judge's own machine. No fixed throughput target is promised, because the machine is unknown.

**Deferred, and explicitly not in this specification**

- Exposing the engine as a service other tools can call over a protocol.
- A second demonstration in a different subject area, beyond the documented example required by FR-035.
- Entering Track 01, which would need an agent that acts on multi-hop findings.
