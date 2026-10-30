# ADR 0006: A deterministic offline model ships in the box

## Status

Accepted.

## Context

Every flow worth building calls a model. If the product only worked with a hosted provider
key, then `make up && make demo`, the test suites, the end-to-end tests, the screenshots and
a first evaluation would all need a paid account and the network, and every run would give
a different answer, so tests could only assert that something came back. The workspace
rule for these projects is stricter still: everything runs locally with no cloud account
and no paid API key.

## Decision

- `providers/offline` is a real provider behind the same `ChatProvider` interface as the
  hosted ones. It parses the request (system prompt, messages, tools, response schema),
  works out what is being asked, and answers with the matching technique: tool calls
  (`tools.py`), a filled JSON schema (`structured.py`), a label from the candidates the
  prompt names (`classify.py`), a summary or action items (`summarize.py`), or templated
  writing (`draft.py`). The same request always gets the same response.
- Nodes name their model with a reference: `offline`, `openai:<model>` (any
  OpenAI-compatible endpoint through `OPENAI_BASE_URL`) or `ollama:<model>` (`OLLAMA_URL`).
  The registry refuses references the deployment has not configured.
- `offline` is the default and the model every template and demo flow uses. The UI labels it
  "Offline" wherever a model is shown, and its costs come from a configurable simulated price
  (`OFFLINE_PRICE_INPUT`, `OFFLINE_PRICE_OUTPUT`) and are flagged as simulated everywhere.
- `OFFLINE_DELAY_MS_PER_100_TOKENS` paces answers like a hosted model (150 in the local
  stack, so live traces have something to show; 0 in tests). The answers are the same either
  way.
- The API serves the offline model over the OpenAI Chat Completions format
  (`/api/v1/offline/v1`), so exported Python scripts run offline too
  ([ADR 0007](0007-python-export-embeds-the-runtime.md)).

## Consequences

Positive:

- The whole product works on a laptop with the network unplugged: demo, tests, e2e,
  screenshots, exported scripts.
- Tests assert exact outputs (a ticket classified `billing` with priority `high`), and the
  exporter tests can require a script's outputs to equal the engine's.
- Swapping a node to a hosted model is a dropdown change; nothing else in the flow moves.

Trade-offs:

- The offline model is heuristic, not intelligent. It handles the shapes of request the
  templates use (classification, extraction, summaries, drafting, tool selection) and gives
  plain answers to anything else. It is labelled so nobody mistakes it for a hosted model.
- Its heuristics are code to maintain; the unit tests pin their behaviour on realistic
  samples.

## Alternatives considered

- **Recorded responses (cassettes).** Exact, but only for the prompts that were recorded:
  editing a template or building a new flow breaks them.
- **A small local model (Ollama) as the default.** Real language ability, but a multi-GB
  download, slow on a CPU-only laptop, and still not deterministic enough for exact
  assertions. It remains a supported provider.
- **A stub that echoes the prompt.** Deterministic, but flows that branch on a
  classification or call tools would show nothing meaningful.
