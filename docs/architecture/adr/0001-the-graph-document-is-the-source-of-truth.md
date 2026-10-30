# ADR 0001: One versioned graph document is the flow

## Status

Accepted.

## Context

A flow is edited on a canvas, validated as the person types, executed by the worker,
published as immutable versions, exported as JSON and as Python, and imported into other
workspaces and deployments. If each of those used its own representation (canvas state,
normalised node and edge tables, an execution format, an export format), every feature
would need a converter, and every converter is a place for the canvas and the engine to
disagree about what a flow means.

## Decision

- A flow is one JSON document, `GraphDocument` in `engine/graph.py`:
  `{schema_version, nodes: [{id, type, position, label, config, settings}], edges:
  [{id, source, source_handle, target, target_handle}], viewport}`.
- The draft lives in `flows.graph` (JSONB) with a `draft_revision` counter; each published
  version is a copy in `flow_versions.graph` with its SHA-256, never updated.
- The same document is validated (`engine/validate.py`), compiled into an execution plan
  (`engine/plan.py`), exported (`{"format": "agentstudio.flow", "format_version": 1,
  ...}` around the graph) and imported. The web app converts it to and from React Flow
  state in one module (`apps/web/src/lib/graph.ts`), and that conversion is unit tested.
- Saving accepts a graph with validation issues (people save half-built flows) but refuses
  one that breaks the document's shape or size limits. Publishing refuses errors.
- Node ids are stable, human-readable identifiers (`classify`, `crm_lookup`) restricted to
  `[a-z][a-z0-9_]*`, because templates reference them (`{{classify.output.category}}`) and
  the exporter turns them into Python names.

## Consequences

Positive:

- What the canvas shows, what the worker runs and what an export contains are the same
  bytes, so there is nothing to keep in sync.
- Versions, imports and exports are trivial copies, and a run always knows the exact graph
  it ran: a draft run keeps a snapshot, a version run points at an immutable version.
- Autosave is one `PUT` of the document with an optimistic revision check.

Trade-offs:

- Questions across flows ("which flows call this URL?") need JSONB queries instead of
  joins; none is on a hot path today.
- Format changes need a `schema_version` bump and an upgrade step on read.
- The whole draft is written on every autosave (bounded by the 512 KB limit).

## Alternatives considered

- **Normalised `nodes` and `edges` tables.** Easier ad hoc queries, but every save becomes a
  diff and versions become copies of many rows.
- **Storing React Flow's own state.** Ties the engine and the export format to a UI library
  and its upgrade cycle.
- **A code-first definition (Python or YAML) rendered on a canvas.** Familiar to engineers,
  but round-tripping canvas edits into code is fragile, and the canvas is the product.
