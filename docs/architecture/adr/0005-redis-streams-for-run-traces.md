# ADR 0005: Live traces are Redis streams replayed over server-sent events

## Status

Accepted.

## Context

The run inspector and the canvas show a run as it happens: each step lights up, and its
inputs, outputs, latency, tokens and cost appear as soon as it ends. The process that
executes a run (a worker) is never the process that serves the browser (an API task),
browsers connect late or reconnect after a network blip, and an API task can be replaced at
any moment. The page loads the run's current state first and subscribes second, so events
published in between must not be lost.

## Decision

- Every run has one Redis stream, `run:<id>:events`. The worker's recorder appends an entry
  (`run.queued`, `run.started`, `step.started`, `step.progress`, `step.waiting`,
  `step.finished`, `run.waiting`, `approval.decided`, `approval.expired`, `run.cancelled`,
  `run.finished`) right after the matching Postgres write.
- `GET /runs/{id}/events` serves the stream as server-sent events. The SSE `id` is the
  stream entry id, so a reconnecting `EventSource` sends `Last-Event-ID` and the API resumes
  with `XREAD` from exactly that entry. A comment every 15 seconds keeps proxies from closing
  the connection; a connection ends after `run.finished` or after five minutes, and the
  browser reconnects transparently.
- Streams are capped (about 5,000 entries), expire 24 hours after a run finishes, and
  expire after seven days in any case. When a stream is gone, the endpoint rebuilds the
  same events from the run's rows in Postgres.
- The web app's reducer (`apps/web/src/lib/trace.ts`) applies events idempotently, so a
  replay never double counts.

## Consequences

Positive:

- No event is lost between loading a run and subscribing, and a reconnect resumes exactly
  where it stopped, on any API task.
- Workers and API tasks need no direct connection to each other; the ALB idle timeout (130
  seconds) is longer than the keep-alive interval.
- Losing Redis loses only live traces in flight; every step is still in Postgres.

Trade-offs:

- Trace entries are written twice (Postgres and Redis); the Redis copy is bounded and
  short-lived.
- SSE is one-way; cancelling a run is a separate `POST`.

## Alternatives considered

- **Redis `PUBLISH` and `SUBSCRIBE`.** No history, so events published before the
  subscription (or during a reconnect) are lost; the client would have to re-fetch and merge.
- **WebSockets.** Two-way, which the trace does not need, and harder to run through load
  balancers and proxies than plain HTTP streaming.
- **Polling the run.** Simple, but either slow or expensive, and it hides how long each step
  really took.
