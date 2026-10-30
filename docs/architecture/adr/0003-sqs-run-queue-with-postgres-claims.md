# ADR 0003: Runs travel on SQS as pointers; Postgres claims make delivery idempotent

## Status

Accepted.

## Context

A run can take seconds or many minutes, pause for a person for days, and must survive
deploys and crashed workers without running a step twice where it can be avoided. The API
must answer `202` immediately and scale separately from the processes that execute runs.
Queues deliver at least once, and a worker can die at any moment, including between
claiming a run and finishing it.

## Decision

- The run row in Postgres is the source of truth. A queue message carries only
  `{run_id, workspace_id}`.
- In deployments the queue is SQS with a dead-letter queue after ten receives, encrypted
  with the deployment's KMS key (Floci locally, see [ADR 0004](0004-floci-for-local-aws.md)).
- A worker claims a run with one conditional update (`status = 'queued'` to `'running'`,
  `claims + 1`). Only one claim can win, so a duplicated, replayed or stale message is
  deleted without effect.
- While a run executes, the worker heartbeats the row every 15 seconds and extends the
  message's visibility, so a long run is never handed to a second worker.
- One elected worker reaps every 30 seconds: runs whose heartbeat is older than 90 seconds
  are re-queued and resume from their last finished step, a run that lost its worker five
  times is failed (`worker_lost`), and a run still `queued` five minutes after its last send
  is sent again (its message was lost, or SQS was unreachable when it started). The row is
  the outbox, so a run that is stored is never failed because a send failed.
- On SIGTERM a worker stops receiving, gives in-flight runs a grace period, then hands the
  rest back (status `queued`, message visible at once).
- `QUEUE_BACKEND=inline` executes runs as background tasks in the API process, for tests and
  quick local work; production refuses it.

## Consequences

Positive:

- Delivery is effectively exactly-once per claim, with at-least-once delivery underneath;
  no distributed lock is needed.
- API and workers scale independently; CloudWatch alarms fire when the oldest queued run
  waits too long, when anything reaches the dead-letter queue, and when no worker is
  running.
- Crashes, deploys, lost messages and poison messages all have a defined outcome.

Trade-offs:

- Steps that were running when a worker died run again on resume (at-least-once per
  step); HTTP steps with side effects should be idempotent or sit behind an approval.
- Two systems to reason about (SQS and Postgres) instead of one.
- A lost message delays its run by up to five minutes.

## Alternatives considered

- **Postgres as the queue** (`SELECT ... FOR UPDATE SKIP LOCKED`). One system fewer and
  transactional enqueueing, but polling load on the primary database grows with workers,
  and it gives up SQS's visibility timeouts, dead-letter queue and native metrics.
- **Celery or RQ on Redis.** Mature, but Redis here is a cache that may lose data; the queue
  would need durability settings Redis is not configured for.
- **A workflow engine (Temporal, Step Functions).** Durable execution for free, but a heavy
  dependency for a self-hosted product that must run on a laptop with `make up`.
