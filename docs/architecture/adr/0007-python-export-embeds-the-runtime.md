# ADR 0007: The Python exporter embeds the engine's runtime and is tested against the engine

## Status

Accepted.

## Context

"Export to Python" is a promise that a flow built on the canvas can leave AgentStudio and run
as ordinary code: in a notebook, a cron job, another service. A script that only resembles
the flow is worse than none, because it fails quietly where the semantics differ
(templates, filters, conditions, merges after branches, loops, retries, tool calls). Flows
can also come from other people through import, so whatever they contain must never become
code in the generated script.

## Decision

- `export/python.py` generates one readable script with four parts: a docstring explaining
  how to run it and its environment variables; the engine's own `engine/runtime.py`,
  embedded verbatim (templates, filters, conditions, the calculator, JSON transforms); small
  helpers for the model API, tools and node semantics; and `run_flow()`, one commented block
  per node in the order the engine plans them.
- The script needs `httpx` and `jmespath`. Model calls go to any OpenAI-compatible endpoint
  (`LLM_BASE_URL`); by default the deployment's offline endpoint, so it runs with no
  provider key. Secrets come from `SECRET_<NAME>` variables, knowledge search and the sandbox
  from the AgentStudio API (`AGENTSTUDIO_URL`, `AGENTSTUDIO_API_KEY`), approvals from the
  terminal or `APPROVAL_MODE`.
- Nothing a user typed is written as code: values are `repr()` literals, comments are one
  sanitised line, identifiers come from validated node ids.
- Unit tests export every template, run each script against an in-process AgentStudio and
  assert its outputs equal the engine's for the same inputs; integration tests run exported
  scripts as real programs against a live API server with the offline model. A
  hostile-strings test checks that injected quotes, newlines and calls stay data.

## Consequences

Positive:

- The exported script behaves like the engine because it runs the engine's own expression
  code, and the test suite proves it for every template on every change.
- The script is a readable artefact (one block per node, comments naming the node) that
  people can edit and own.

Trade-offs:

- Every change to node semantics must land in both the engine and the exporter's helpers;
  the equivalence tests catch drift, but the work is real.
- The embedded runtime makes scripts a few hundred lines longer than a hand-written
  equivalent.
- Live traces, versions and the approvals inbox stay in AgentStudio; the script prints its
  results.

## Alternatives considered

- **A pip-installable runtime package.** Shorter scripts, but a dependency to version and
  publish, and a script that breaks when the package moves on.
- **Generating idiomatic code per node with no shared runtime.** Nicer to read, but
  templates and conditions would be re-implemented per node and drift from the engine.
- **Exporting only JSON for an AgentStudio runner.** Exact, but not "Python you own".
