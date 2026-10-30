# Architecture decision records

Each record states a decision that shapes AgentStudio, the context that led to it, what it
costs, and what else was considered. Records are immutable once accepted; a change of mind
is a new record that supersedes the old one.

| ADR | Decision | Status |
| --- | --- | --- |
| [0001](0001-the-graph-document-is-the-source-of-truth.md) | One versioned JSON graph document is the flow: stored, validated, executed, imported and exported as is | Accepted |
| [0002](0002-one-api-image-three-roles.md) | One API image runs the API, the worker and the CLI; the web app is a second image configured at runtime | Accepted |
| [0003](0003-sqs-run-queue-with-postgres-claims.md) | Runs travel on SQS as pointers; Postgres claims make delivery idempotent | Accepted |
| [0004](0004-floci-for-local-aws.md) | Develop against the Floci AWS emulator, provisioned by the production Terraform modules | Accepted |
| [0005](0005-redis-streams-for-run-traces.md) | Live traces are Redis streams replayed over server-sent events | Accepted |
| [0006](0006-deterministic-offline-provider.md) | A deterministic offline model ships in the box, behind the same interface as real providers | Accepted |
| [0007](0007-python-export-embeds-the-runtime.md) | The Python exporter embeds the engine's own runtime and is tested against the engine | Accepted |
| [0008](0008-approvals-release-the-worker.md) | A run waiting for a person holds no worker; it is re-queued and resumed from its steps | Accepted |
| [0009](0009-workspaces-as-the-tenant-boundary.md) | Workspaces are the tenant boundary, enforced per request and in every repository query | Accepted |
| [0010](0010-a-closed-expression-language-instead-of-code-nodes.md) | Flows compute with a closed expression language, never with user code | Accepted |

## Template

```markdown
# ADR NNNN: <decision in one line>

## Status

Proposed | Accepted | Superseded by ADR NNNN

## Context

## Decision

## Consequences

## Alternatives considered
```
