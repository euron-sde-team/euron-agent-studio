# ADR 0009: Workspaces are the tenant boundary, enforced per request and in every query

## Status

Accepted.

## Context

One AgentStudio deployment serves several teams. Their flows, runs, approvals, knowledge
bases, secrets and API keys must never cross: a leak of a secret or a run's customer data to
another team is the worst failure this product can have. People also belong to several
teams, and automation (API keys, webhooks) must be confined the same way people are.

## Decision

- A **workspace** owns everything: every tenant table has a `workspace_id` with a foreign
  key, and composite indexes lead with it.
- People join workspaces through `memberships` with one role each (`owner`, `editor`,
  `viewer`). API keys belong to one workspace with role `viewer` or `editor`; webhooks belong
  to one flow.
- Every workspace route takes the workspace (id or slug) in its path. One dependency
  (`WorkspaceAccess` in `api/deps.py`) resolves it from the caller's membership, or from the
  API key's own workspace, and checks the route's minimum role before the handler runs.
  Anyone else gets `404`, never `403`, so workspace ids and slugs cannot be probed.
- Services receive the resolved workspace, and every repository query filters by
  `workspace_id`, including lookups by a globally unique id. Engine ports are bound to the
  run's workspace (knowledge search, the model response cache).
- `tests/integration/test_isolation.py` builds a workspace with one of everything and
  sweeps every workspace route with an outsider's session and with another workspace's API
  key, and replays every id in a second workspace.

## Consequences

Positive:

- One rule, enforced in one dependency and checked by one sweep, instead of per-route
  reasoning.
- People switch workspaces without signing in again; automation is confined by
  construction.
- Deleting a workspace removes everything it owns through cascades, plus its stored files.

Trade-offs:

- Isolation is application-level. A repository query that forgot its `workspace_id` filter
  would leak; the isolation sweep and code review are the guard. Postgres row-level
  security would add a second line of defence and is on the roadmap.
- All tenants share tables, caches and workers, so a busy workspace can slow others within
  its limits (`MAX_ACTIVE_RUNS_PER_WORKSPACE`).

## Alternatives considered

- **A schema or a database per tenant.** Stronger isolation, but migrations, connection
  pools and cross-tenant operations multiply with the number of workspaces.
- **Row-level security as the only mechanism.** Strong, but it needs a session variable per
  transaction and makes every query depend on it; planned as an addition, not a
  replacement.
- **One deployment per team.** The strongest isolation, available today by running more
  stacks, but heavy for small teams.
