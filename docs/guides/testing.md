# Testing

AgentStudio has five suites, from milliseconds to minutes. Each one owns a layer, and the
browser suites run against the real stack seeded by `make demo`.

| Suite | Command | Count | Runs against |
| --- | --- | --- | --- |
| API unit | `make test` (with the web unit tests) | 216 | Nothing: pure modules, fakes for the ports |
| API integration | `make test-integration` | 72 | Real PostgreSQL 16, Valkey 8 and Floci (S3, SQS) on ports 9121 to 9123 |
| Web unit | `make test` | 39 | The web app's pure logic (`apps/web/src/lib`), in Node |
| End to end | `make e2e` | 22 | The running stack in Chromium |
| QA crawl | `make qa` | 4 | Every page, desktop and mobile, with axe |

The API suites cover 81% of `agentstudio` (statements and branches, measured with
`coverage run -m pytest tests`).

## API unit tests

```bash
make test                                                     # API unit + web unit
uv --directory apps/api run pytest tests/unit -q              # API unit only
uv --directory apps/api run pytest tests/unit/test_executor.py -k secret -q
```

`apps/api/tests/unit` covers the modules that hold the product's rules:

| Area | Files |
| --- | --- |
| Graph validation and planning | `test_validation.py`, `test_plan.py` |
| The executor: parallel branches, skips and merges, loops, retries, timeouts, cancellation, pause and resume, secret masking, payload caps | `test_executor.py` |
| The template language, conditions, the calculator, JSON transforms | `test_runtime_templates.py`, `test_runtime_conditions.py`, `test_runtime_calculator.py`, `test_runtime_helpers.py` |
| The offline model, on realistic samples | `test_offline_provider.py`, `test_offline_parsing.py` |
| Provider adapters against mocked HTTP, pricing, the registry and its per-workspace cache | `test_providers.py` |
| The outbound network guard (private ranges, redirects, rebinding) and the sandbox | `test_http_guard.py`, `test_sandbox.py`, `test_integrations.py` |
| Every template runs and produces what its description promises | `test_templates.py` |
| The Python exporter: every template's script reproduces the engine; hostile strings stay data; scripts run as programs | `test_export.py` |

## API integration tests

```bash
make test-integration       # starts the dependencies if needed, then runs the suite
make test-deps-down         # stops them
```

`scripts/test-deps.sh` runs PostgreSQL, Valkey and Floci as their own compose project
(`agentstudio-test`, `deploy/compose/compose.test.yaml`) on ports 9121 to 9123, with tmpfs
storage, so they never touch the main stack. The suite migrates a fresh schema, creates its
bucket and queues, and drives the real app through `httpx`:

| Area | File |
| --- | --- |
| Sign-in, sessions, lockout, password changes, CSRF | `test_auth.py` |
| Workspaces, members and roles | `test_workspaces.py` |
| API keys | `test_api_keys.py` |
| Flows: drafts and revisions, publishing, versions, import and export | `test_flows.py` |
| Runs: inputs, waiting, failures, secret masking, re-runs, limits, live traces over SSE and their replay from PostgreSQL | `test_runs.py` |
| Approvals, decisions and expiry | `test_approvals.py` |
| The SQS worker: duplicates, lost workers, lost messages, an unreachable queue, graceful hand-back | `test_worker.py` |
| Knowledge on S3 and full-text search | `test_knowledge.py` |
| Secrets | `test_secrets.py` |
| Signed webhooks and replays | `test_webhooks.py` |
| Every template, and exported scripts run as programs against a live server | `test_templates.py` |
| The dashboard | `test_dashboard.py` |
| Workspace isolation: every route, with an outsider's session and another workspace's key | `test_isolation.py` |

To point the suite at other services, set `TEST_DATABASE_URL`, `TEST_REDIS_URL` and
`TEST_AWS_ENDPOINT_URL`.

## Web unit tests

```bash
pnpm --filter @agentstudio/web test            # all
pnpm --filter @agentstudio/web test -- graph   # files matching "graph"
```

Vitest covers the editor's pure logic: the node catalog, graph conversion and connection
rules, auto-layout, undo history, reference suggestions, the trace reducer, run timelines,
trigger descriptions, Python literals for code snippets, and formatting.

## End-to-end tests

```bash
make up && make demo
make e2e
pnpm --filter @agentstudio/e2e test -- tests/editor.spec.ts   # one file
```

Playwright drives Chromium against `http://localhost:3120` as the demo people (the password
comes from `deploy/compose/.env`). The 22 tests sign in and out, check roles, build a flow
by dragging and wiring nodes, validate it, run it and read the live trace, undo and tidy up,
decide approvals, inspect failed runs and re-run them, filter run history, export JSON and
Python and import a flow back, upload knowledge and search it, manage API keys, secrets,
webhooks and members, replace a temporary password, create flows from templates and read
the dashboard. Sessions are saved in `e2e/.auth` after the first sign-in per person, because
the API allows ten sign-ins a minute per address.

## QA crawl

```bash
make qa
```

`e2e/qa/crawl.spec.ts` visits every page, signed out and signed in, at 1440x900 and 390x844.
It fails on console errors, failed requests, horizontal scrolling, broken links and serious
or critical axe violations (WCAG 2.1 A and AA). Review the pages it captures in
`e2e/test-results` when it fails.

## Screenshots

```bash
make screenshots
```

`e2e/capture/screens.spec.ts` captures the README screenshots at 1440x900 and twice the pixel
density into `docs/assets/screenshots/`, and `capture/make-gif.mjs` turns them into
`docs/assets/tour.gif`. Capture on a freshly seeded stack, so the pages show the demo data
and nothing the end-to-end tests created.

## Static checks

```bash
make lint        # ruff (lint and format), ESLint, Prettier
make typecheck   # mypy (strict) and tsc
make sanitize    # credentials and cloud identifiers in committable files
make tf-fmt tf-validate tf-lint tf-security
```

## Continuous integration

`.github/workflows/checks.yml` runs on every push and pull request: ruff, mypy and the API
unit tests; ESLint, Prettier, tsc and the web unit tests; Terraform formatting and
validation for every environment; and the sanitization scan. The heavier workflows in
`.github/workflows-full/` are opt-in (move them into `.github/workflows/` to enable them):
the integration suite on PostgreSQL, Valkey and Floci with the web build and the OpenAPI
check, gitleaks, CodeQL and dependency audits, tflint and checkov, multi-architecture image
builds, and the full stack on Floci with the end-to-end suite and the QA crawl.
