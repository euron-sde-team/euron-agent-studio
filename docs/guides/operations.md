# Operations

Day-two tasks for a running AgentStudio: what to watch, what the alarms mean, how to scale,
rotate keys, back up and recover. The commands assume the AWS deployment from
[deploy-aws.md](deploy-aws.md); the same signals exist on the local stack.

## Health

| Endpoint | Process | Meaning |
| --- | --- | --- |
| `GET /livez` | API | The process answers. The load balancer and the container health check use it |
| `GET /readyz` | API | Database, Valkey, storage and queue all reachable: `200 {"status": "ready"}`, otherwise `503` with the failing check named |
| `GET /metrics` | API (inside the VPC only) | Prometheus metrics of that task |
| `:9100/metrics` | worker | Prometheus metrics of that worker; its container health check reads it |
| `GET /env.js` | web | The web app's health check |

## Metrics

Both processes export Prometheus metrics (scrape them from inside the VPC, for example with
an ADOT or Prometheus sidecar). The useful ones:

| Metric | Labels | Watch for |
| --- | --- | --- |
| `agentstudio_http_requests_total`, `agentstudio_http_request_duration_seconds` | method, route template, status | Error rates and latency per route |
| `agentstudio_runs_started_total` | trigger (`manual`, `api`, `webhook`, `rerun`) | Traffic by source |
| `agentstudio_runs_finished_total` | status | A rise in `failed` |
| `agentstudio_run_duration_seconds` | | Long executions approaching `RUN_TIMEOUT_S` |
| `agentstudio_active_runs` | | Saturation: near `WORKER_CONCURRENCY` on every worker means add workers |
| `agentstudio_steps_total`, `agentstudio_step_duration_seconds` | node type, status | Which kind of step fails or is slow |
| `agentstudio_model_calls_total`, `agentstudio_model_call_duration_seconds` | provider, outcome (`ok`, `error`, `cached`) | Provider outages and slowness |
| `agentstudio_tokens_total`, `agentstudio_cost_usd_total` | provider | Spend |
| `agentstudio_http_tool_requests_total` | outcome (`ok`, `http_error`, `blocked`, `error`) | `blocked` means flows tried to reach private addresses |
| `agentstudio_webhook_deliveries_total` | outcome | Rejected signatures and replays |
| `agentstudio_reaped_total` | kind (`run`, `message`, `approval`) | `run`: workers dying mid-run; `message`: queue messages lost |

## Logs

Every process logs one JSON object per line: `timestamp`, `level`, `logger`, `event`, and on
the API the `request_id` that is also returned in the `X-Request-Id` header and in every
error body. On AWS each service writes to `/agentstudio/<name_prefix>/<service>` (encrypted
with the deployment's KMS key). To follow one failed request in CloudWatch Logs Insights:

```text
fields @timestamp, level, event, logger
| filter request_id = "<the id from the error>"
| sort @timestamp asc
```

Events worth an alert of your own: `run_crashed`, `run_abandoned`, `run_send_deferred`,
`reaper_failed`, `queue_receive_failed`, `readiness_check_failed`.

## Alarms

The `observability` module sends these to the SNS topic (and to `alarm_email` when set):

| Alarm | Meaning | What to do |
| --- | --- | --- |
| `<service>: 5xx responses` | The API or the web app returned server errors | Find the `request_id` in the error body or the log, then the `unhandled_error` line |
| `<service>: tasks failing health checks` | Tasks are not answering `/livez` (`/env.js` for web) | Check the service's events and the task's last log lines; a crash loop is usually configuration (the boot refusal lists every problem) |
| `<service>: CPU` or `memory sustained above 85%` | The service is saturated | Raise its maximum task count or its size; autoscaling already follows CPU |
| `Workers: no task running` | Nothing executes queued runs | Check the worker service's events; runs wait safely in the queue |
| `Run queue: the oldest queued run has waited ...` | Runs are queuing faster than workers execute them | Add workers (`worker_max_count`) or raise `WORKER_CONCURRENCY`; check that workers are not failing every run |
| `Run queue: messages moved to the dead-letter queue` | A message failed ten receives | See [Dead letters](#dead-letters) |
| `Database CPU`, `free storage`, `connections` | The database is saturated or filling up | Resize the instance or storage; check connections against the pools below |

The CloudWatch dashboard named after the deployment shows requests and errors, latency, workers
and queue age, the database, and CPU and memory per service.

## Scaling

| Lever | Where | Notes |
| --- | --- | --- |
| API tasks | `api_min_count`, `api_max_count` (module inputs) | Stateless; scale on CPU |
| Worker tasks | `worker_min_count`, `worker_max_count` | Stateless; each runs `WORKER_CONCURRENCY` runs at once |
| Runs per worker | `WORKER_CONCURRENCY` (`worker_concurrency` input) | Runs mostly wait on models and HTTP, so a worker can run more than it has vCPUs |
| Per-workspace ceiling | `MAX_ACTIVE_RUNS_PER_WORKSPACE` | Keeps one busy workspace from filling every worker |
| Database connections | `DATABASE_POOL_SIZE`, `DATABASE_MAX_OVERFLOW` | Keep `tasks x (pool + overflow)` for API and workers together under the instance's `max_connections` |

## Runs that need attention

- **Stuck `running`.** A run whose worker vanished has no heartbeat; within about two
  minutes the reaper hands it out again and it resumes from its last finished step. After
  five losses it fails with `worker_lost` (`run_abandoned` in the log).
- **Stuck `queued`.** A run whose queue message was lost (or whose start could not reach
  SQS) is sent again by the reaper five minutes after its last send (`run_message_resent`).
- **Waiting for approval.** Waiting runs hold nothing. Approvals with a deadline expire on
  their own; others wait until someone decides or someone cancels the run.
- **Cancel** from the run page or `POST /runs/{id}/cancel`. A running run notices within half
  a second and stops the steps in flight; a queued or waiting run is cancelled at once.

### Dead letters

Queue messages are only pointers to runs, so a dead-lettered message has no work in it.
Look at the run ids it names:

```bash
aws sqs receive-message --queue-url <dlq url> --max-number-of-messages 10 --attribute-names All
```

Each run has already been retried by the reaper or failed with a recorded error; open it in
the app to see which. Once the cause (usually the database or a bad deploy) is fixed, purge
the dead-letter queue.

## Keys and secrets

On AWS the application secrets live in one Secrets Manager secret, `<name_prefix>/app`
(JSON with `SESSION_SECRET`, `API_KEY_PEPPER`, `ENCRYPTION_KEY`). Terraform generates them
once and then ignores their value, so a rotation you make by hand persists.

| Rotate | Effect | How |
| --- | --- | --- |
| `SESSION_SECRET` | Everyone is signed out | Put a new random value (32+ characters) in the secret, then restart the API: `aws ecs update-service --cluster <cluster> --service <api service> --force-new-deployment` |
| `API_KEY_PEPPER` | Every API key stops working; issue new ones | As above, for the API and the workers |
| `ENCRYPTION_KEY` | Stored secrets and webhook signing secrets become unreadable | No in-place rotation: set the new key, then re-enter every secret and rotate every webhook. Do this only if the key leaked |
| Database password | None | RDS rotates it in its managed secret; the app reads it per connection |
| A workspace secret or an API key | Only that credential | In the app: **Settings, Secrets** or **API keys** |

Rotate one at a time, and never `SESSION_SECRET` and `API_KEY_PEPPER` to the same value
(production refuses that).

## Backups and recovery

| Data | Protection | Recovery |
| --- | --- | --- |
| PostgreSQL (everything that matters) | Automated RDS backups (3 days in dev, 14 in prod) with point-in-time restore; Multi-AZ in prod | Restore to a new instance, then point `DATABASE_URL` at it |
| Knowledge originals (S3) | Versioning, SSE-KMS | Restore an object version. The searchable chunks are in PostgreSQL, so a database restore brings search back too |
| Valkey | None needed: traces in flight, caches, rate-limit windows | Lost data rebuilds itself; finished runs replay their traces from PostgreSQL |
| `ENCRYPTION_KEY` | Your own copy (it is in Secrets Manager, with a recovery window) | Without it, stored secrets cannot be decrypted |

## Upgrades

`make aws-deploy` from the new commit; migrations run on API boot under an advisory lock,
and workers hand their runs back before they stop. See
[deploy-aws.md](deploy-aws.md#updating) for rollouts and rollbacks.
