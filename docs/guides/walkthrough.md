# Walkthrough: one support ticket, from webhook to approved reply

This tour follows one run of the *Support ticket triage* flow through the code, so you can
see how the pieces fit before you change one. Every step names the files to open. Paths are
relative to `apps/api/src/agentstudio/` unless they start with `apps/web/` or `infra/`.

Run the stack first (`make up && make demo`) and open the flow as Leo
(`leo.chen@northwind.example`) to follow along on the canvas.

## 0. The flow

The flow was created from a template (`templates/catalog.py`, slug `support-triage`) and
published, so it exists as two things: an editable draft in `flows.graph` and an immutable
copy in `flow_versions.graph`. Both are the same JSON document, `GraphDocument` in
`engine/graph.py` ([ADR 0001](../architecture/adr/0001-the-graph-document-is-the-source-of-truth.md)):

```text
start --> classify (Prompt, JSON: category, priority, sentiment, summary) --> search_help (Knowledge) --+
start --> lookup_customer (HTTP GET to the CRM) ----------------------------------------------------+--> draft_reply (Prompt)
draft_reply --> needs_review (Condition: priority high or urgent, or an enterprise plan)
needs_review --review--> approve (Human approval) --approved--> sent / --rejected--> escalated
needs_review --else----> auto_reply
```

**Things to notice:**

- Publishing (`services/flows.py`) validates the draft with `engine/validate.py` and refuses
  errors. Every issue carries a severity, a code and, where it applies, the node, edge and
  field it concerns, which is how the editor shows it inline.
- The CRM is `https://sandbox.agentstudio.test/crm/contacts`, a fixture API answered in
  process (`integrations/sandbox/app.py`), which is why the template runs offline.

## 1. A signed webhook arrives

The helpdesk posts the ticket to `POST /api/v1/hooks/{hook_id}`.

| Layer | Code |
| --- | --- |
| Route | `api/routes/hooks.py`: path pattern, a per-hook rate limit, a 256 KB body cap |
| Service | `services/webhooks.py` `WebhookService.deliver` |
| Crypto | `core/crypto.py`: the flow's signing secret is decrypted (AES-GCM, bound to the flow), then `verify_webhook` checks the HMAC and the timestamp in constant time |

`deliver` answers the same `404` for unknown, disabled and secretless hooks, remembers each
accepted signature in Valkey (`hook:seen:<sha256>`) so a replay gets `409`, and starts a run
of the published version with the JSON body as inputs.

## 2. The run is stored and queued

`services/runs.py` `RunService.start` is shared by every trigger (the editor, API keys,
webhooks, re-runs):

1. resolves the version and compiles the plan (`engine/plan.py` `build_plan`), which also
   lists the secrets the flow references;
2. validates the inputs against the Start step's fields (`engine/runtime.py`
   `validate_inputs`);
3. refuses a workspace already at `MAX_ACTIVE_RUNS_PER_WORKSPACE`;
4. inserts the run as `queued`, publishes `run.queued` to the run's Valkey stream
   (`integrations/trace.py`), and puts `{run_id, workspace_id}` on SQS
   (`integrations/queue.py` `send_or_defer`).

The webhook answers `202` with the run. If SQS were unreachable, the run would still be
stored, and the reaper would send it later
([ADR 0003](../architecture/adr/0003-sqs-run-queue-with-postgres-claims.md)).

## 3. A worker claims it

`worker.py` long-polls SQS and hands each message to `RunExecution.execute` in
`services/runs.py`:

| Step | Code |
| --- | --- |
| Claim | `repositories/runs.py` `claim`: `UPDATE runs SET status = 'running', claims = claims + 1 ... WHERE id = ... AND status = 'queued' RETURNING *`. A duplicate message loses this race and is deleted |
| Secrets | `services/secrets.py`: only the names the plan references are decrypted |
| Resume state | `resume_state`: rebuilt from `run_steps` and decided approvals (empty on the first claim) |
| Ports | `EngineServices`: `WorkspaceModels` (`providers/registry.py`), `WorkspaceKnowledge` (`services/knowledge.py`), the guarded HTTP client, `RedisCancel` |
| Recorder | `DbRecorder`: writes `run_steps` and publishes trace events as steps start and finish |

While the run executes, the worker heartbeats the row every 15 seconds and extends the
message's visibility.

## 4. The engine walks the graph

`engine/executor.py` `Executor.execute` runs the plan as a DAG: every node whose inputs have
resolved starts at once (bounded by `MAX_PARALLEL_STEPS`), each under its own timeout and
retry policy. The handlers are in `engine/nodes.py`:

| Node | Handler | What happens |
| --- | --- | --- |
| `classify` | `LlmHandler` | The prompt is rendered (`engine/runtime.py` `render`), the model registry resolves `offline`, and the offline provider (`providers/offline/classify.py`, `structured.py`) fills the JSON fields. The step records tokens and a simulated cost |
| `lookup_customer` | `HttpHandler` | Runs in parallel with `classify`. `integrations/http.py` would refuse private addresses; this host is the in-process sandbox |
| `search_help` | `KnowledgeHandler` | `repositories/knowledge.py` searches the help center with PostgreSQL full text (`websearch_to_tsquery`, ranked by `ts_rank_cd`), inside the run's workspace only |
| `draft_reply` | `LlmHandler` | Waits for both branches; drafts the reply from the ticket, the customer record and the articles |
| `needs_review` | `ConditionHandler` | Evaluates the route's rules (`in_list` on the priority, `equals` on the plan) and fires the `review` handle; `auto_reply` is skipped, and the skip propagates |

Before anything is recorded, `_Masker` replaces every resolved secret value with
`[secret:NAME]`, and `cap_payload` truncates values above `MAX_STEP_PAYLOAD_KB`.

## 5. The run pauses for a person

`approve` is a Human approval node. `prepare_approval` (`engine/nodes.py`) renders its title
(`Review reply: {{inputs.subject}}`) and message (the drafted reply); the executor asks the
recorder for an approval (`DbRecorder.approval_requested` inserts the `approvals` row, with a
48-hour deadline) and marks the step `waiting`. With nothing else able to progress, the
executor returns `waiting`; `RunExecution.finalize` stores that, and the worker deletes the
message and frees its slot
([ADR 0008](../architecture/adr/0008-approvals-release-the-worker.md)).

## 6. The browser watches it live

Anyone looking at the run sees each step as it happens:

| Layer | Code |
| --- | --- |
| Route | `api/routes/runs.py`: `GET /runs/{id}/events`, server-sent events with `X-Accel-Buffering: no` |
| Service | `services/events.py`: replays the stream from `Last-Event-ID` (or the start) with `XREAD`, blocks for new entries, sends a keep-alive every 15 seconds, and rebuilds the events from PostgreSQL once a stream has expired |
| Browser | `apps/web/src/lib/use-run-stream.ts` (one `EventSource` per run), `apps/web/src/lib/trace.ts` `applyEvent` (an idempotent reducer) |
| UI | `apps/web/src/components/editor/canvas-node.tsx` (status rings on the canvas), `apps/web/src/components/editor/run-panel.tsx`, `apps/web/src/components/runs/timeline.tsx` |

## 7. A reviewer approves

Ava opens **Approvals** (`apps/web/src/app/w/[workspace]/approvals/page.tsx`), reads the
drafted reply in `apps/web/src/components/runs/approval-card.tsx`, and approves.

| Layer | Code |
| --- | --- |
| Route | `api/routes/approvals.py`: `POST /approvals/{id}/decision`, editors and owners, and a signed-in person (API keys cannot decide) |
| Service | `services/approvals.py` `ApprovalService.decide`: locks the approval row, records the decision and an activity entry, sets the run back to `queued`, publishes `approval.decided` and sends the run to the queue |

## 8. The run resumes and finishes

A worker claims the run again (`claims` is now 2). `resume_state` restores every finished
step and the decision, so nothing already done runs twice; the executor resolves `approve`
from the decision and continues on the `approved` handle to `sent`. `RunExecution.finalize`
totals tokens and cost from the steps, stores the outputs (masked like everything else),
publishes `run.finished` and shortens the stream's lifetime to a day.

## 9. And as a script

`GET /flows/{id}/export/python` (`export/python.py`) turns the same plan into a standalone
script: the engine's `engine/runtime.py` embedded verbatim, helpers for the model API and
tools, and one commented block per node in plan order. `apps/api/tests/unit/test_export.py`
proves, for every template, that the script's outputs equal the engine's
([ADR 0007](../architecture/adr/0007-python-export-embeds-the-runtime.md)).

## Where to go next

- Add a node type: `engine/graph.py` (config model and `NODE_SPECS`), `engine/nodes.py`
  (handler), `engine/validate.py`, `export/python.py`, and in the web app
  `apps/web/src/lib/nodes.ts` and `apps/web/src/components/editor/forms.tsx`.
- Add a model provider: implement `ChatProvider` (`providers/base.py`) and register it in
  `providers/registry.py`.
- The design behind all of this: [HLD.md](../architecture/HLD.md) and
  [LLD.md](../architecture/LLD.md).
