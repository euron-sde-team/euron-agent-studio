# API guide

Everything the web app does goes through this REST API. [`openapi.json`](openapi.json) is
exported from the application itself (`make openapi`), and a running API serves the same
document interactively at `/docs`. This page covers what the reference does not: how to
authenticate, the conventions every endpoint shares, and the common tasks.

Base URL: `http://localhost:8120` locally, `https://api.<domain>` on AWS. Every path below
starts with `/api/v1`.

## Authentication

| Caller | How |
| --- | --- |
| The web app | `POST /auth/login` sets an `httpOnly` session cookie. Unsafe requests with the cookie must come from the web app's origin |
| A script or another system | A workspace API key: `Authorization: Bearer agst_...`. Owners create keys under **Settings, API keys** (or `POST /workspaces/{workspace}/api-keys`); the secret is shown once |
| A webhook sender | No key: the `X-AgentStudio-Signature` header signs each delivery (see [Webhooks](#webhooks)) |

A session token also works as a bearer token. API keys carry the `viewer` or `editor` role in
one workspace; they cannot manage members, secrets or keys, or decide approvals.

## Conventions

- **Workspaces** appear in the path by id or slug: `/workspaces/northwind-operations/...`.
  A workspace you cannot see answers `404`, never `403`.
- **Lists** take `limit` (1 to 100) and `offset` and return
  `{"items": [...], "total": n, "limit": l, "offset": o}`.
- **Errors** always have one shape, with the request id that also appears in the
  `X-Request-Id` header and in the server log:

  ```json
  {"error": {"code": "invalid_inputs", "message": "subject is required.", "request_id": "01J..."}}
  ```

  `details` is added when there is more to say, for example the list of validation issues
  that block publishing.

- **Rate limits** answer `429` with `Retry-After`; limited endpoints also send
  `X-RateLimit-Limit`, `X-RateLimit-Remaining` and `X-RateLimit-Reset`.
- **Times** are ISO 8601 in UTC; **costs** are US dollars.

## Run a flow

```bash
KEY=agst_...    # an editor key of the workspace
WS=northwind-operations
FLOW=<flow id>  # from GET /workspaces/$WS/flows

curl -sS -X POST "http://localhost:8120/api/v1/workspaces/$WS/flows/$FLOW/runs?wait=30" \
  -H "Authorization: Bearer $KEY" -H "content-type: application/json" \
  -d '{"inputs": {"subject": "Refund please", "body": "I was charged twice.", "customer_email": "dana@globex.example"}}'
```

- `version` in the body chooses what runs: `"auto"` (the default: the published version, or
  the draft of a flow never published), `"published"`, `"draft"`, or a version number.
- The answer is `202` with the run. With `?wait=N` (at most `MAX_RUN_WAIT_S`, 30 seconds by
  default) the API holds the request until the run finishes, pauses for an approval, or `N`
  seconds pass, and returns the run as it is then: check `status` (`queued`, `running`,
  `waiting`, `succeeded`, `failed`, `cancelled`) and `outputs` or `error`.
- `GET /workspaces/{workspace}/runs/{run_id}` returns the run with every step (inputs,
  outputs, tokens, cost, attempts, tool calls), the graph it ran and its approvals.
- `POST .../runs/{run_id}/cancel` and `POST .../runs/{run_id}/rerun` do what they say.

## Follow a run live

`GET /workspaces/{workspace}/runs/{run_id}/events` is a server-sent event stream:

```bash
curl -N -H "Authorization: Bearer $KEY" \
  "http://localhost:8120/api/v1/workspaces/$WS/runs/<run id>/events"
```

Each event has an `id` (send it back as `Last-Event-ID` to resume after a disconnect), a
type (`run.started`, `step.started`, `step.progress`, `step.finished`, `run.waiting`,
`approval.decided`, `run.finished`, ...) and a JSON `data` payload. The stream ends after
`run.finished`; finished runs replay their whole trace.

## Decide an approval

Approvals are decided by people (a signed-in session, not an API key):

```bash
curl -sS -X POST "http://localhost:8120/api/v1/workspaces/$WS/approvals/<approval id>/decision" \
  -H "Cookie: agentstudio_session=..." -H "Origin: http://localhost:3120" \
  -H "content-type: application/json" -d '{"decision": "approve", "comment": "Looks right"}'
```

The paused run continues on the `approved` or `rejected` branch.

## Webhooks

Enable a flow's webhook (`PUT /workspaces/{workspace}/flows/{flow_id}/webhook`, or
**Triggers** in the editor) to get its URL and signing secret. Each delivery is a `POST` to
`/api/v1/hooks/{hook_id}` with the JSON inputs as the body and this header:

```text
X-AgentStudio-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256 of "<t>.<raw body>" keyed with the secret>
```

Deliveries older than five minutes, replayed signatures and bodies over 256 KB are refused.
A webhook always runs the published version. The [quickstart](../guides/quickstart-local.md#things-to-try)
has a `curl` and `openssl` example; the editor shows a Python one.

## Export

- `GET /workspaces/{workspace}/flows/{flow_id}/export` returns a portable JSON document;
  `POST /workspaces/{workspace}/flows/import` takes it back (into any workspace or
  deployment).
- `GET /workspaces/{workspace}/flows/{flow_id}/export/python` returns a standalone script
  that reproduces the flow with `httpx` ([ADR 0007](../architecture/adr/0007-python-export-embeds-the-runtime.md)).

## The offline model over the OpenAI format

`POST /offline/v1/chat/completions` serves the built-in deterministic model in the OpenAI
Chat Completions format, with any workspace API key, so exported scripts and other
OpenAI-compatible tools can use it with no provider key.
