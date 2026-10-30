# ADR 0008: A run waiting for a person holds no worker

## Status

Accepted.

## Context

A Human approval step can wait minutes or days. Workers have a fixed number of run slots
(`WORKER_CONCURRENCY`), and a deploy replaces every worker. If a paused run kept its slot,
its memory and its queue message, a handful of unanswered approvals would starve every
other run, and any deploy would have to wait for people to answer.

## Decision

- When a run reaches an approval node, the engine renders the request (title, message, the
  context the reviewer needs), stores an `approvals` row and marks the step `waiting`. Other
  branches keep running.
- When nothing else can progress, the executor returns `waiting`. The worker marks the run
  `waiting`, deletes its queue message and frees the slot. A paused run is only rows in
  Postgres.
- A decision (`POST /approvals/{id}/decision`, a signed-in person only) records who decided
  and why, sets the run back to `queued` and sends it again. Any worker claims it, rebuilds
  the run's state from its recorded steps, resolves the approval step from the decision, and
  continues on the `approved` or `rejected` branch.
- Approvals can expire (`expires_after_hours` on the node). The reaper marks them expired,
  which counts as a rejection, and the run continues on the rejected branch.
- The executor is resumable in general: the same mechanism resumes runs after a crashed or
  stopped worker ([ADR 0003](0003-sqs-run-queue-with-postgres-claims.md)).

## Consequences

Positive:

- Thousands of runs can wait for people at no cost; worker capacity is spent only on runs
  that can progress.
- Deploys never wait for approvals, and a decision can be executed by any worker.
- One resume path covers approvals, crashes and deploys, so it is exercised constantly.

Trade-offs:

- Resumption rebuilds state from recorded steps, which are JSON, masked and capped. After a
  resume, later steps see `[secret:NAME]` where an earlier output contained a secret value,
  and a marked preview of any output above the 256 KB step cap. Flows that pass very large
  payloads across an approval should store them elsewhere and pass a reference.
- A resumed run starts on a fresh worker, so the decision adds a queue hop and a claim
  before the run continues (well under a second locally).

## Alternatives considered

- **Keep the run's coroutine alive and wait on an event.** Simple code, but a slot per
  waiting run, lost on every deploy or crash.
- **Snapshot the executor's in-memory state.** Faster resume, but a second serialisation
  format to keep compatible across versions; the recorded steps already hold everything.
