# Troubleshooting

Start with the request id: every API response carries `X-Request-Id`, every error body
repeats it as `error.request_id`, and every log line of that request includes it.

```bash
make logs SERVICE=api | grep <request id>
```

## The stack

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `Cannot connect to the Docker daemon` | Docker (or Colima) is not running | Start it, then `make up` |
| `run make env first` | `deploy/compose/.env` is missing or incomplete | `make env` |
| `port is already allocated` | Another program uses one of 3120, 8120, 5452, 6412, 4612, 9120 | Override the port in `deploy/compose/.env` ([quickstart](quickstart-local.md#port-clashes)) |
| `terraform` exits non-zero | Provisioning the emulator failed | `make logs SERVICE=terraform`, then `make down && make up` |
| `migrate` exits non-zero | PostgreSQL unreachable, or a migration failed | `make logs SERVICE=migrate` |
| The API restarts with `Refusing to start in production` | `APP_ENV=production` with unsafe settings | The message lists every problem; fix them all ([configuration.md](configuration.md)) |
| `/readyz` answers `503` | One dependency is down | The body names it: `database`, `redis`, `storage` or `queue` |

## Signing in

| Symptom | Cause | Fix |
| --- | --- | --- |
| "Email or password is incorrect." | Wrong email or password | Demo accounts use `AGENTSTUDIO_DEMO_PASSWORD` from `deploy/compose/.env` |
| "Too many failed sign-ins. Try again in N minute(s)." | Eight wrong passwords locked the account | Wait 15 minutes; the lock lifts on its own |
| `429` on sign-in | More than 10 attempts a minute from one address | Wait a minute. The browser suites save sessions in `e2e/.auth` to stay under this; delete the folder if those sessions are stale |
| "Sign-up is closed on this deployment." | Sign-up only creates the first account | Ask an owner to add you, or set `ALLOW_SIGNUP=true` |
| The web app says the API cannot be reached | The API is down, or the web app points elsewhere | `make ps`; check `API_URL` on the web container |
| `403` with code `csrf` | A cookie request came from an origin not in `CORS_ORIGINS` or `WEB_URL` | Add the origin you use (for example a LAN address) to `CORS_ORIGINS` |

## Runs

| Symptom | Cause | Fix |
| --- | --- | --- |
| A run stays `queued` | No worker is consuming the queue | `make logs SERVICE=worker`; on AWS, the worker service's events. A run whose message was lost is sent again after five minutes |
| `429` with `too_many_active_runs` | The workspace has `MAX_ACTIVE_RUNS_PER_WORKSPACE` runs queued or running | Wait, cancel runs, or raise the limit |
| A step fails with `blocked_address` | An HTTP request step tried a private, loopback or metadata address | Use a public endpoint, or list the host in `HTTP_ALLOWED_HOSTS` |
| A step fails with `model_unavailable` | The node names a model this deployment has not configured | Pick another model, or configure the provider ([configuration.md](configuration.md#model-providers)) |
| A step fails with `timeout` | The step ran longer than its own timeout (step settings) | Raise the step's timeout, or check the slow dependency |
| A run fails with `run_timeout` | The run executed longer than `RUN_TIMEOUT_S` | Find the slow step in the timeline; raise the limit if the flow is legitimately long |
| `invalid_inputs` when starting a run | The inputs do not match the Start step's fields | The message names the field; the run dialog shows what the flow expects |
| A run fails with `worker_lost` | It lost its worker five times | Look for crashes in the worker log around the run's id (`run_crashed`), for example a worker running out of memory |
| The live trace stops updating | A proxy buffers or cuts the event stream | The API sends `X-Accel-Buffering: no` and a keep-alive every 15 seconds; keep proxy idle timeouts above that. Reloading the page replays the trace |
| Output shows `[secret:NAME]` | Secret values are masked in everything a run records | Working as designed; the step received the real value |

## Webhooks

| Response | Code | Cause |
| --- | --- | --- |
| `401` | `signature_missing` | No `X-AgentStudio-Signature` header |
| `401` | `signature_invalid` | The header is malformed, or the HMAC does not match: sign the exact raw body, as `<timestamp>.<body>`, with the current secret |
| `401` | `signature_expired` | The timestamp is more than five minutes from the server's clock |
| `409` | `replayed` | The same signature was already accepted |
| `404` | `not_found` | Unknown hook, webhook disabled, or the flow has no signing secret |
| `413` | `payload_too_large` | The body is over 256 KB |

## Exported scripts

| Symptom | Fix |
| --- | --- |
| `ModuleNotFoundError: httpx` or `jmespath` | `pip install httpx jmespath` |
| `401` from the offline model or knowledge search | Set `AGENTSTUDIO_API_KEY` to a key of the flow's workspace |
| Calls go to the wrong server | Set `AGENTSTUDIO_URL` (and `LLM_BASE_URL` for another model endpoint) |
| An HTTP step sends an empty token | Set `SECRET_<NAME>` for each secret the flow uses |
| The script waits at an approval | It asks on the terminal; set `APPROVAL_MODE=approve` or `reject` to answer in advance |

## Tests

| Symptom | Fix |
| --- | --- |
| Integration tests cannot connect | `scripts/test-deps.sh up` (or `make test-integration`, which starts them); ports 9121 to 9123 must be free |
| End-to-end tests fail at sign-in | Run `make demo` first; delete `e2e/.auth` after `make down` |
| A browser test fails only under load | Re-run the file alone (`pnpm --filter @agentstudio/e2e test -- tests/<file>`); check `e2e/test-results` for the trace |
