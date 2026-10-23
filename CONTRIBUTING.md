# Contributing

Thanks for helping improve Euron AgentStudio. This guide covers the workflow, the bar a
change has to clear, and the conventions the codebase follows.

## Ground rules

- **Open an issue first** for anything larger than a bug fix or a docs tweak, so we can
  agree on the approach before you invest time.
- **One concern per pull request.** A refactor and a feature are two PRs.
- **Security issues go through private reporting**, never a public issue. See
  [SECURITY.md](SECURITY.md).
- By contributing you agree your work is released under the [MIT License](LICENSE).

## Development setup

Requirements: Docker with Compose v2, Python 3.12 with [uv](https://docs.astral.sh/uv/), and
Node.js 22 with pnpm 9 (`corepack enable`).

```bash
make up          # Postgres, Redis, the AWS emulator (provisioned by Terraform), api, worker, web
make demo        # a demo workspace with template flows, knowledge bases and real runs
make test        # unit tests for the API (pytest) and the web app (Vitest)
```

[docs/guides/quickstart-local.md](docs/guides/quickstart-local.md) walks through the local
stack in detail.

## Before you open a pull request

Each of these must pass:

```bash
make lint typecheck test
make test-integration                  # the API against real Postgres, Redis and the AWS emulator
make e2e                               # when you touched a user flow, the web app or infrastructure
make tf-validate tf-lint tf-security   # when you touched infra/terraform
make sanitize                          # no credentials, account ids or resource ids
```

## Conventions

**Layers (api).** Routes declare the URL, the request and response models and the access
dependency, nothing else. Services hold the business rules, transactions and cache
invalidation. Repositories are the only code that touches the database.
[apps/api/README.md](apps/api/README.md) has the rules and a reference resource to copy.

**Workspace isolation is structural.** Every repository method that reads workspace data
takes the workspace id as a required argument and filters by it, and the access dependency
resolves the caller's role before a route runs. The integration suite calls every workspace
route as a non-member and asserts that nothing is returned or changed.

**The engine is pure where it can be.** Graph validation, templating, conditions, the
calculator, JSON transforms, the offline model and the Python exporter take plain data and
return plain data, so they are unit tested without a database. A new node type needs a
config model in `engine/graph.py`, validation rules, an executor in `engine/nodes/`, an
exporter case in `export/python.py`, an inspector form in the web app, and tests for each.

**Exports must stay runnable.** Every template flow is exported to Python and executed by
the test suite against the offline provider; the script's outputs must equal the engine's.

**Configuration is validated.** A new environment variable is declared in
`apps/api/src/agentstudio/core/config.py` and documented in
[docs/guides/configuration.md](docs/guides/configuration.md) in the same PR.
Security-relevant settings are enforced at boot when `APP_ENV=production`.

**Database changes are new migrations.** `uv run alembic revision -m "describe it"` in
`apps/api`. Never edit an applied migration.

**Comments explain why.** The code says what it does. Comments are for the constraint, the
incident, or the trade-off that made it this way.

**Style.** ruff (lint and format) and mypy in strict mode for Python; ESLint, Prettier and
strict TypeScript for the web app.

## Commit messages

Imperative mood with a scope: `engine: retry upstream 429s with jitter`,
`web: show tool calls in the run inspector`. Explain the *why* in the body when it is not
obvious.

## Architecture decisions

A change that alters a documented decision (execution model, queueing, trace transport,
model providers, export format, deployment topology) needs a new ADR in
[docs/architecture/adr/](docs/architecture/adr/), using the existing ones as a template.
