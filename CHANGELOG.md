# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-30

First public release.

### Added

- A visual flow editor (Next.js, React Flow): a node palette, drag and drop, typed
  connections, an inspector with a form per node type and a reference picker for
  `{{ ... }}` templates, inline validation on nodes, edges and fields, undo and redo,
  automatic layout, autosave with revision checks, and dark mode.
- Twelve node types: Start, Prompt, Agent with tools, HTTP request, Knowledge search,
  Calculator, JSON transform, Condition, Loop, Human approval, Output and Note.
- An asynchronous DAG executor: parallel branches, skip propagation and merges, loops with
  per-item concurrency, per-step timeouts and retries with back-off, continue-on-error,
  cancellation, and pause and resume for approvals, crashes and deploys.
- Runs from the editor, from code with workspace API keys (`?wait=` for synchronous
  callers), and from HMAC-signed webhooks with replay protection; re-runs; run history with
  filters; a run inspector with a timeline, every step's inputs, outputs, tokens, cost and
  tool calls.
- Live traces over server-sent events from per-run Redis streams, resumable with
  `Last-Event-ID` and replayed from PostgreSQL for old runs.
- An approvals inbox with deadlines; decisions by people only.
- Model providers behind one interface: a deterministic offline model (the default, no key
  needed), any OpenAI-compatible endpoint and Ollama, with per-call token and cost
  accounting and a per-workspace response cache.
- Knowledge bases of Markdown and text documents, stored in S3 and searched with PostgreSQL
  full-text search.
- Versions with publish and restore, JSON import and export, and export to a standalone
  Python script that embeds the engine's runtime and reproduces the flow.
- Six templates (support triage with approval, invoice extraction, research brief, lead
  qualification, meeting actions, HR policy assistant) and `make demo`, which seeds a
  workspace with two weeks of real runs.
- Workspaces with owner, editor and viewer roles, members, encrypted write-only secrets,
  an activity log, a dashboard, and password changes from the account menu.
- Security controls: Argon2id passwords, account lockout and per-IP sign-in limits, session
  revocation, CSRF origin checks, peppered API key hashes, AES-256-GCM secrets bound to
  their rows, a connect-time outbound network guard against server-side request forgery,
  secret masking in everything a run records, and boot-time refusal of unsafe production
  settings.
- A run queue on SQS with a dead-letter queue, conditional claims, heartbeats, a reaper that
  re-queues runs whose worker vanished and resends lost messages, and graceful hand-back on
  shutdown.
- Terraform for AWS (VPC, RDS, ElastiCache Valkey, S3, SQS, KMS, Secrets Manager, ECR, ECS
  Fargate behind one load balancer, an optional WAF, alarms and a dashboard) in `aws-dev`
  and `aws-prod`, and a local stack on the Floci AWS emulator provisioned by the same
  modules.
- Unit, integration, browser end-to-end and accessibility QA suites, README screenshots
  and a tour GIF captured from the seeded stack, and architecture, security and operations
  documentation.
