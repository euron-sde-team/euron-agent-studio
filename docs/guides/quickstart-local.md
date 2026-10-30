# Quickstart: run Euron AgentStudio locally

This guide starts the complete stack on your machine: the web app, the API, the run worker,
PostgreSQL, Valkey (Redis-compatible), and an AWS emulator provisioned by the same Terraform
modules that build production. You need no AWS account and no model provider key: every
template runs on the built-in offline model.

## Prerequisites

| Requirement | Notes |
| --- | --- |
| Docker with Compose v2 | `make up` uses `docker compose ... up --wait` |
| GNU Make and `openssl` | `make env` generates local secrets with `openssl rand` |
| About 5 GB of free disk and 4 GB of free memory | For the images, volumes and the running stack |
| Free host ports | 3120, 8120, 5452, 6412, 4612 and 9120, all bound to `127.0.0.1` (see [Port clashes](#port-clashes)) |
| Node 22, pnpm 9, Python 3.12 and `uv` | Only to run the tests or the apps outside Docker. The repository pins Node in `.nvmrc`, pnpm in `package.json` and Python in `.python-version` |

## Start the stack

From the repository root:

```bash
make up
```

This does three things:

1. `make env` writes `deploy/compose/.env` with random, local-only secrets (once; it never
   overwrites an existing file).
2. Builds the `api` and `web` images and starts every service.
3. A one-shot `terraform` container applies `infra/terraform/envs/local-floci` to the
   emulator (the KMS key `alias/agentstudio-local`, the knowledge bucket with SSE-KMS, the
   run queue with its dead-letter queue, the application secret), then the `migrate`
   one-shot applies the database migrations, and the API, the worker and the web app start.

When it finishes it prints the URLs. Then seed the demo data:

```bash
make demo
```

`make demo` creates the **Northwind Operations** workspace with four people, six flows built
from the templates (one with a second published version, one with a webhook), a knowledge
base per flow that needs one, secrets, API keys, and about two weeks of real run history:
every demo run was executed by the engine on the offline model, including approvals that
were approved, rejected or are still waiting for you. It also creates a second, smaller
workspace, *Leo's experiments*.

## Sign in

Open <http://localhost:3120>. Every demo account uses the same password,
`AGENTSTUDIO_DEMO_PASSWORD` from `deploy/compose/.env` (`make demo` prints it):

```bash
grep AGENTSTUDIO_DEMO_PASSWORD deploy/compose/.env
```

| Who | Email | Role in Northwind |
| --- | --- | --- |
| Ava Martin | `ava.martin@northwind.example` | owner |
| Leo Chen | `leo.chen@northwind.example` | editor (and owner of *Leo's experiments*) |
| Sam Rivera | `sam.rivera@northwind.example` | editor |
| Maya Patel | `maya.patel@northwind.example` | viewer |

The seed refuses to run with `APP_ENV=production` and does nothing if the demo workspace
already has flows.

## What runs where

| Service | URL or port | What it is |
| --- | --- | --- |
| web | <http://localhost:3120> | The flow editor, runs, approvals, knowledge, templates and settings |
| api | <http://localhost:8120/docs> | The API with its interactive reference; `GET /livez` (process) and `GET /readyz` (database, Valkey, storage and queue) |
| worker | <http://localhost:9120/metrics> | Executes runs from the queue; Prometheus metrics |
| postgres | `localhost:5452` | PostgreSQL 16, database, user and password `agentstudio` |
| valkey | `localhost:6412` | Live traces, rate limits, caches |
| floci | <http://localhost:4612> | AWS emulator: SQS, S3, KMS, Secrets Manager |

The API runs with `APP_ENV=development`: the local stack talks to an emulator and links to
`localhost`, both of which production refuses on purpose.

```bash
make ps                    # service status
make logs SERVICE=worker   # tail one service (api, worker, web, migrate, postgres, valkey, floci, terraform)
```

## Things to try

1. **Watch a run live.** As Leo, open **Flows**, then *Support ticket triage*, and press
   **Run** with the sample input. Each step lights up on the canvas as it runs, and the run
   panel under the canvas fills in inputs, outputs, tokens and cost.
2. **Decide an approval.** The sample ticket (a duplicate charge) is classified high
   priority, so the run pauses before the reply goes out. Open **Approvals**, read the
   drafted reply, and approve it: the run continues on the approved branch.
3. **Build something.** Create a flow, drag a Prompt and an Output from the palette, connect
   them, and type `{{` in the prompt to pick a reference. Problems show inline as you type;
   **Tidy up** lays the graph out.
4. **Export to Python.** On any flow, choose **Export to Python** and run the script:

   ```bash
   pip install httpx jmespath
   AGENTSTUDIO_URL=http://localhost:8120 AGENTSTUDIO_API_KEY=<a viewer key> python support_ticket_triage.py
   ```

   It calls the deployment's offline model and sandbox, so it runs offline too. Create the
   key under **Settings, API keys** as Ava.
5. **Call it from code.** Start a run with an API key and wait for the result:

   ```bash
   curl -sS -X POST "http://localhost:8120/api/v1/workspaces/northwind-operations/flows/<flow id>/runs?wait=30" \
     -H "Authorization: Bearer agst_..." -H "content-type: application/json" \
     -d '{"inputs": {"subject": "Refund please", "body": "I was charged twice.", "customer_email": "dana@globex.example"}}'
   ```

6. **Send a signed webhook.** In a flow's **More actions** menu, open **Triggers: API and
   webhook**, enable the webhook and copy its URL and signing secret, then:

   ```bash
   SECRET=whsec_...; URL=http://localhost:8120/api/v1/hooks/<hook id>
   BODY='{"subject": "Refund please", "body": "I was charged twice.", "customer_email": "dana@globex.example"}'
   T=$(date +%s)
   SIG=$(printf '%s.%s' "$T" "$BODY" | openssl dgst -sha256 -hmac "$SECRET" -hex | sed 's/^.* //')
   curl -sS -X POST "$URL" -H "content-type: application/json" \
     -H "X-AgentStudio-Signature: t=$T,v1=$SIG" --data "$BODY"
   ```

## Use a real model

The offline model is the default. To add a hosted or local model, put the provider in
`deploy/compose/.env` and restart:

```bash
cat >> deploy/compose/.env <<'ENV'
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=sk-...
# or a local Ollama:
OLLAMA_URL=http://host.docker.internal:11434
ENV
make up
```

The models then appear in every Prompt and Agent step's model picker (`openai:gpt-4o-mini`,
`ollama:llama3.2`, ...), next to `offline`. See [configuration.md](configuration.md#model-providers).

## Stop and reset

```bash
make down
```

This stops every container and deletes the volumes: the database, the emulator's data and
the local Terraform state. The next `make up` starts from scratch. `deploy/compose/.env` is
kept; delete it if you want new secrets.

## Troubleshooting

### Port clashes

Every host port can be overridden in `deploy/compose/.env`:

```bash
cat >> deploy/compose/.env <<'ENV'
AGENTSTUDIO_WEB_PORT=3220
AGENTSTUDIO_API_PORT=8220
AGENTSTUDIO_PG_PORT=5552
AGENTSTUDIO_REDIS_PORT=6512
AGENTSTUDIO_FLOCI_PORT=4712
AGENTSTUDIO_WORKER_METRICS_PORT=9220
ENV
make down && make up
```

The API's `CORS_ORIGINS`, `WEB_URL` and `PUBLIC_API_URL` and the web app's `API_URL` are
derived from these variables in `compose.yaml`, so they stay consistent. The URLs `make up`
prints read the same variable names from your shell, not from the file; export them there
too if you change them.

### Other problems

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `run make env first` from Compose | `deploy/compose/.env` is missing or incomplete | `make env` (or delete the file and run it again) |
| `make up` waits, then `terraform` exited non-zero | Provisioning the emulator failed | `make logs SERVICE=terraform`, then `make down && make up` |
| `migrate` exited non-zero | Postgres was not reachable, or a migration failed | `make logs SERVICE=migrate` |
| `The demo workspace already exists; nothing to do.` | The seed only fills an empty demo workspace | `make down && make up && make demo` |
| The sign-in page says the API cannot be reached | The API is not running or the port changed | `make ps`, then `make logs SERVICE=api` |

More in [troubleshooting.md](troubleshooting.md).

## Next steps

- Follow one run through the code: [walkthrough.md](walkthrough.md)
- Run the test suites: [testing.md](testing.md)
- Run the local containers against real AWS resources: [local-with-aws.md](local-with-aws.md)
- Deploy to AWS: [deploy-aws.md](deploy-aws.md)
- Understand the system: [HLD.md](../architecture/HLD.md)
