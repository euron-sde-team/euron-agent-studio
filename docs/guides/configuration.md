# Configuration

Every setting comes from the environment and is validated once at boot by
`apps/api/src/agentstudio/core/config.py` (pydantic-settings). A wrong type or an
out-of-range value stops the process with a message naming the variable. With
`APP_ENV=production`, the API also refuses to start while any unsafe value remains
(development secrets, `*` origins, cookies without `Secure`, local storage, the inline queue,
an emulator endpoint, private networks open to flows) and lists every problem at once.

Where the values come from:

| Environment | Source |
| --- | --- |
| Local stack (`make up`) | `deploy/compose/compose.yaml` and `compose.floci.yaml`, with secrets and port overrides from `deploy/compose/.env` (`make env`) |
| Local containers on real AWS (`make up-aws`) | The same, plus `deploy/compose/.env.aws` ([local-with-aws.md](local-with-aws.md)) |
| AWS (`make aws-deploy`) | The `deployment` Terraform module: plain values in the task definitions, secrets from Secrets Manager ([deploy-aws.md](deploy-aws.md)) |
| Tests | `tests/integration/conftest.py` builds `Settings` directly |

## Application

| Variable | Default | Meaning |
| --- | --- | --- |
| `APP_ENV` | `development` | `development`, `test` or `production`. Production turns on the boot checks above, HSTS and secure cookies |
| `PRODUCT_NAME` | `Euron AgentStudio` | Shown in the API's metadata and, through the web app's own variable, in the UI |
| `LOG_LEVEL` | `info` | `debug`, `info`, `warning` or `error` |
| `LOG_FORMAT` | `json` | `json` (one object per line, with `request_id`) or `console` |
| `CORS_ORIGINS` | `http://localhost:3120,http://127.0.0.1:3120` | Comma-separated origins allowed to call the API with credentials. Unsafe requests with a cookie must come from one of these (or `WEB_URL`) |
| `WEB_URL` | `http://localhost:3120` | The web app's address |
| `PUBLIC_API_URL` | `http://localhost:8120` | The API's public address: webhook URLs and exported scripts are built from it |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | Read by uvicorn: peers trusted to set `X-Forwarded-For`. On AWS, the VPC range |

## Database and cache

| Variable | Default | Meaning |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+asyncpg://agentstudio:agentstudio@localhost:5452/agentstudio` | PostgreSQL 16 (asyncpg driver) |
| `DATABASE_SECRET_ARN` | none | On AWS: the RDS-managed secret holding the password, read for each new connection so a rotation needs no redeploy |
| `DATABASE_POOL_SIZE` | `10` | Connections per process |
| `DATABASE_MAX_OVERFLOW` | `10` | Extra connections under bursts |
| `DATABASE_ECHO` | `false` | Log every SQL statement (debugging only) |
| `MIGRATE_ON_BOOT` | `false` | Apply pending migrations when the API starts (under an advisory lock). Terraform sets it to `true`; the local stack runs a `migrate` one-shot instead |
| `REDIS_URL` | `redis://localhost:6412/0` | Valkey or Redis: live traces, cancel flags, rate limits, session revocation, webhook replay guards, caches. `rediss://` for TLS |

## Sessions, keys and encryption

| Variable | Default | Meaning |
| --- | --- | --- |
| `SESSION_SECRET` | a development value | Signs session tokens. Production: random, at least 32 characters, different from the pepper |
| `SESSION_TTL_HOURS` | `168` | Session lifetime (7 days) |
| `API_KEY_PEPPER` | a development value | HMAC key for stored API keys. Changing it invalidates every key |
| `ENCRYPTION_KEY` | a development value | Base64 of 32 random bytes (`openssl rand -base64 32`): encrypts secrets and webhook signing keys. Keep it: losing it makes them unreadable |
| `COOKIE_SECURE` | `false` | `Secure` session cookies; required in production |
| `COOKIE_DOMAIN` | none | Cookie domain, when the API must share the cookie across subdomains (not needed for `app.` and `api.` of one domain) |
| `ALLOW_SIGNUP` | `false` | Open self-service sign-up. Off: only the first account can sign up; owners add everyone else |
| `WEBHOOK_TOLERANCE_S` | `300` | How old a webhook signature may be |
| `DEMO_PASSWORD` | none | Password for the accounts `agentstudio demo seed` creates |

## Knowledge storage

| Variable | Default | Meaning |
| --- | --- | --- |
| `STORAGE_BACKEND` | `local` | `s3` (required in production) or `local` |
| `STORAGE_DIR` | `data/files` | Directory for `local` |
| `S3_BUCKET` | none | Knowledge bucket |
| `S3_KMS_KEY_ID` | none | KMS key for SSE-KMS uploads |
| `AWS_REGION` | `us-east-1` | Region for S3, SQS and Secrets Manager |
| `AWS_ENDPOINT_URL` | none | An emulator endpoint (Floci); production refuses it |
| `MAX_DOCUMENT_KB` | `2048` | Largest knowledge document |

## Run queue and worker

| Variable | Default | Meaning |
| --- | --- | --- |
| `QUEUE_BACKEND` | `inline` | `sqs` (required in production) or `inline` (the API runs flows itself; tests and quick local work) |
| `SQS_QUEUE_URL` | none | The run queue |
| `WORKER_CONCURRENCY` | `4` | Runs one worker executes at a time |
| `WORKER_SHUTDOWN_GRACE_S` | `60` | On SIGTERM, how long in-flight runs may finish before they are handed back |
| `WORKER_METRICS_PORT` | `0` (off) | Port of the worker's Prometheus endpoint (`9100` in compose and on AWS) |
| `HEARTBEAT_S` | `15` | How often a running run proves its worker is alive |
| `STALE_RUN_S` | `90` | After this long without a heartbeat, the reaper re-queues the run |

## Engine limits

| Variable | Default | Meaning |
| --- | --- | --- |
| `RUN_TIMEOUT_S` | `900` | Longest a run may execute (waiting for approval does not count) |
| `MAX_PARALLEL_STEPS` | `4` | Steps of one run executing at once |
| `MAX_NODES` | `200` | Nodes per flow |
| `MAX_EDGES` | `400` | Edges per flow |
| `MAX_GRAPH_KB` | `512` | Size of a flow document |
| `MAX_LOOP_ITEMS` | `200` | Items one Loop may process |
| `MAX_AGENT_ITERATIONS` | `10` | Model turns one Agent may take |
| `MAX_STEP_PAYLOAD_KB` | `256` | Recorded size of one step's input or output (larger values are truncated with a marker) |
| `MAX_ACTIVE_RUNS_PER_WORKSPACE` | `20` | Queued plus running runs per workspace |
| `MAX_RUN_WAIT_S` | `30` | Longest `?wait=` a caller may ask for when starting a run |

## HTTP request steps

| Variable | Default | Meaning |
| --- | --- | --- |
| `HTTP_ALLOWED_HOSTS` | empty | Comma-separated host names flows may reach even though they resolve to private addresses |
| `HTTP_ALLOW_PRIVATE_NETWORKS` | `false` | Turn the private-network block off entirely (laptops only; production refuses it) |
| `HTTP_MAX_RESPONSE_KB` | `1024` | Largest response body a step reads |

## Model providers

The offline model is always available. Each configured provider adds its models to every
model picker, referenced as `<provider>:<model>`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `DEFAULT_MODEL` | `offline` | The model new Prompt and Agent steps start with (a workspace can choose its own) |
| `OPENAI_BASE_URL` | none | Any OpenAI-compatible endpoint: OpenAI, Azure-compatible gateways, Groq, Together, vLLM, LM Studio |
| `OPENAI_API_KEY` | none | Its key (on AWS, from Secrets Manager through `provider_secret_arns`) |
| `OPENAI_MODELS` | `gpt-4o-mini,gpt-4.1-mini` | Models offered as `openai:<model>` |
| `OLLAMA_URL` | none | An Ollama server, for example `http://host.docker.internal:11434` |
| `OLLAMA_MODELS` | `llama3.2,qwen3:4b` | Models offered as `ollama:<model>` |
| `MODEL_PRICES` | built-in list prices | JSON: `{"model": [input USD per 1M tokens, output USD per 1M tokens]}`, overriding or extending the defaults |
| `LLM_TIMEOUT_S` | `120` | Timeout of one model call |
| `OFFLINE_PRICE_INPUT`, `OFFLINE_PRICE_OUTPUT` | `0.15`, `0.60` | Simulated price of the offline model per 1M tokens (flagged as simulated everywhere) |
| `OFFLINE_DELAY_MS_PER_100_TOKENS` | `0` | Pace offline answers like a hosted model (the local stack uses 150, so live traces have something to show) |

## Rate limits

Requests per minute, counted in Valkey so every API task shares them.

| Variable | Default | Applies to |
| --- | --- | --- |
| `RATE_LIMIT_LOGIN` | `10` | Sign-in attempts per client IP |
| `RATE_LIMIT_RUNS` | `60` | Starting and re-running runs, per person or API key |
| `RATE_LIMIT_WEBHOOKS` | `120` | Deliveries per webhook |
| `RATE_LIMIT_OFFLINE` | `600` | Calls to the OpenAI-compatible offline endpoint, per person or key |
| `RATE_LIMIT_UPLOAD` | `60` | Knowledge uploads, per person or key |

## Web app

The web image reads these at request time (`/env.js`), so one image serves every
environment.

| Variable | Default | Meaning |
| --- | --- | --- |
| `API_URL` | `http://localhost:8120` | Where browsers reach the API |
| `PRODUCT_NAME` | `Euron AgentStudio` | Name shown in the UI |

## Local stack overrides (`deploy/compose/.env`)

| Variable | Default | Meaning |
| --- | --- | --- |
| `AGENTSTUDIO_SESSION_SECRET`, `AGENTSTUDIO_API_KEY_PEPPER`, `AGENTSTUDIO_ENCRYPTION_KEY` | generated | The three secrets above |
| `AGENTSTUDIO_DEMO_PASSWORD` | generated | Password of every demo account |
| `AGENTSTUDIO_WEB_PORT`, `AGENTSTUDIO_API_PORT`, `AGENTSTUDIO_PG_PORT`, `AGENTSTUDIO_REDIS_PORT`, `AGENTSTUDIO_FLOCI_PORT`, `AGENTSTUDIO_WORKER_METRICS_PORT` | 3120, 8120, 5452, 6412, 4612, 9120 | Host ports, all bound to `127.0.0.1` |
| `AGENTSTUDIO_OFFLINE_DELAY_MS` | `150` | `OFFLINE_DELAY_MS_PER_100_TOKENS` for the local stack |
| `AGENTSTUDIO_LOG_LEVEL`, `AGENTSTUDIO_PRODUCT_NAME` | `info`, `Euron AgentStudio` | Passed through |
| `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OLLAMA_URL` | empty | Optional real models |

## What Terraform sets on AWS

The `deployment` module sets `APP_ENV=production`, `COOKIE_SECURE=true`, the origins and
URLs for `app.<domain>` and `api.<domain>`, `STORAGE_BACKEND=s3` with the bucket and KMS
key, `QUEUE_BACKEND=sqs` with the queue URL, `DATABASE_URL` without a password plus
`DATABASE_SECRET_ARN`, `MIGRATE_ON_BOOT=true`, `FORWARDED_ALLOW_IPS` (the VPC range),
`DEFAULT_MODEL` and `HTTP_ALLOWED_HOSTS`. `SESSION_SECRET`, `API_KEY_PEPPER`,
`ENCRYPTION_KEY` and `REDIS_URL` (with the Valkey auth token) are generated into Secrets
Manager and injected by ECS. Anything else goes through `extra_environment` (plain values)
and `provider_secret_arns` (secrets); see [deploy-aws.md](deploy-aws.md#1-configure-the-environment).
