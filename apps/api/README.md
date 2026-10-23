# AgentStudio API and worker

FastAPI service for Euron AgentStudio, plus the run worker that executes queued runs from
the same image with a different command.

```bash
uv sync                                         # Python 3.12 and every dependency
uv run uvicorn agentstudio.main:create_app --factory --reload --port 8120
uv run python -m agentstudio.worker             # run worker (QUEUE_BACKEND=sqs)
uv run agentstudio --help                       # CLI: migrations, users, demo data, OpenAPI export
uv run pytest tests/unit                        # unit tests, no services needed
```

## Layout

```text
src/agentstudio/
├── main.py            app factory: middleware, routers, lifespan (pools, migrations, providers)
├── worker.py          SQS consumer: claim, execute, heartbeat, reap; graceful shutdown
├── cli.py             typer CLI
├── core/              config, logging, errors, request context, security, crypto, rate limits, metrics
├── db/                engine, session, declarative base, migration runner
├── models/            SQLAlchemy models, one module per aggregate
├── schemas/           Pydantic request and response models
├── repositories/      the only code that touches the database
├── services/          business rules, transactions, cache invalidation, audit events
├── api/               routes and dependencies (authentication, workspace roles, rate limits)
├── engine/            graph models, validation, planning, expressions, executor, node handlers, tools
├── providers/         model interface, the offline provider, OpenAI-compatible and Ollama adapters
├── export/            the Python exporter
├── integrations/      SQS or inline queue, S3 or local storage, Redis trace streams, the sandbox API
├── templates/         the template gallery
└── demo/              demo seed used by `make demo`
```

## The rules

| Layer | May import | Must not |
| --- | --- | --- |
| `api/routes` | schemas, services, `api/deps` | touch a session, a repository or Redis directly |
| `services` | repositories, `engine`, `export`, `providers`, `integrations`, `core` | import FastAPI |
| `repositories` | models, `db` | commit, call a service, or skip the `workspace_id` filter |
| `engine`, `providers`, `export` | `core` and each other | touch the database; the engine reaches storage only through the ports a service hands it |

**Workspace isolation.** Every repository method that reads workspace data takes
`workspace_id` as a required argument. The `WorkspaceAccess` dependency in `api/deps.py`
resolves the caller's role first and answers 404 to non-members, so a workspace's existence
is not revealed either.

**Transactions.** A service method that writes opens and commits its own transaction.
Routes never commit.

**Errors.** Raise the typed errors in `core/errors.py`. The handlers turn them into the one
envelope every response uses:
`{"error": {"code", "message", "request_id", "details?"}}`.

## A reference resource

API keys are the smallest complete slice of the stack. Read them in this order:

1. `api/routes/api_keys.py`: URL, role dependency, request and response models
2. `services/api_keys.py`: generation, hashing with the pepper, audit event, commit
3. `repositories/api_keys.py`: workspace-scoped queries
4. `tests/integration/test_api_keys.py`: the behaviour, including a non-member sweep

## Tests

| Suite | Needs | Run |
| --- | --- | --- |
| `tests/unit` | nothing | `uv run pytest tests/unit` |
| `tests/integration` | Postgres, Redis, the AWS emulator | `make test-integration` from the repo root |
