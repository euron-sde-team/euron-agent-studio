/** API shapes, mirroring apps/api/src/agentstudio/schemas. */

export type Role = "owner" | "editor" | "viewer";
export type RunStatus = "queued" | "running" | "waiting" | "succeeded" | "failed" | "cancelled";
export type StepStatus = "running" | "waiting" | "succeeded" | "failed" | "skipped" | "cancelled";
export type RunTrigger = "manual" | "api" | "webhook" | "rerun";
export type ApprovalStatus = "pending" | "approved" | "rejected" | "expired" | "cancelled";

export type Page<T> = { items: T[]; total: number; limit: number; offset: number };

export type User = {
  id: string;
  email: string;
  name: string;
  is_admin: boolean;
  created_at: string;
  last_login_at: string | null;
};

export type WorkspaceSummary = {
  id: string;
  slug: string;
  name: string;
  role: Role;
  flow_count: number;
  member_count: number;
};

export type Me = { user: User; workspaces: WorkspaceSummary[] };

export type SystemInfo = {
  product_name: string;
  version: string;
  default_model: string;
  providers: string[];
  offline_only: boolean;
  allow_signup: boolean;
  needs_setup: boolean;
  queue_backend: string;
  public_api_url: string;
  sandbox_url: string;
  limits: {
    max_nodes: number;
    max_edges: number;
    max_loop_items: number;
    max_agent_iterations: number;
    run_timeout_s: number;
    max_document_kb: number;
    max_run_wait_s: number;
  };
};

export type WorkspaceSettings = { default_model: string; run_retention_days: number };

export type Workspace = {
  id: string;
  slug: string;
  name: string;
  description: string;
  settings: WorkspaceSettings;
  role: Role;
  created_at: string;
};

export type Member = {
  user_id: string;
  email: string;
  name: string;
  role: Role;
  joined_at: string;
};

export type ApiKey = {
  id: string;
  name: string;
  prefix: string;
  role: "viewer" | "editor";
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
};

export type ApiKeyCreated = ApiKey & { key: string };

export type AuditEvent = {
  id: string;
  action: string;
  target_type: string;
  target_id: string | null;
  details: Record<string, unknown>;
  actor_name: string | null;
  created_at: string;
};

export type Secret = {
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
  last_used_at: string | null;
};

// ---------------------------------------------------------------------------------------
// Flows and the graph document
// ---------------------------------------------------------------------------------------

export type Position = { x: number; y: number };

export type NodeSettings = {
  timeout_s?: number;
  retries?: number;
  retry_backoff_s?: number;
  continue_on_error?: boolean;
  cache_ttl_s?: number;
};

export type GraphNode = {
  id: string;
  type: string;
  position: Position;
  label: string;
  config: Record<string, unknown>;
  settings: NodeSettings;
};

export type GraphEdge = {
  id: string;
  source: string;
  source_handle: string;
  target: string;
  target_handle: string;
};

export type GraphDocument = {
  schema_version: 1;
  nodes: GraphNode[];
  edges: GraphEdge[];
  viewport?: { x: number; y: number; zoom: number } | null;
};

export type Issue = {
  severity: "error" | "warning";
  code: string;
  message: string;
  node_id: string | null;
  edge_id: string | null;
  field: string | null;
};

export type Webhook = {
  enabled: boolean;
  hook_id: string | null;
  url: string | null;
  signature_header: string;
  secret: string | null;
};

export type FlowSummary = {
  id: string;
  name: string;
  description: string;
  tags: string[];
  published_version: number | null;
  latest_version: number;
  draft_revision: number;
  node_count: number;
  node_types: string[];
  template_slug: string | null;
  webhook_enabled: boolean;
  last_run_at: string | null;
  last_run_status: RunStatus | null;
  runs_7d: number;
  success_rate_7d: number | null;
  created_at: string;
  updated_at: string;
};

export type Flow = FlowSummary & {
  graph: GraphDocument;
  draft_updated_at: string;
  issues: Issue[];
  webhook: Webhook;
};

export type DraftSaved = { draft_revision: number; draft_updated_at: string; issues: Issue[] };

export type Version = {
  id: string;
  version: number;
  notes: string;
  graph_sha256: string;
  node_count: number;
  created_by_name: string | null;
  created_at: string;
  published: boolean;
};

export type VersionDetail = Version & { graph: GraphDocument };

export type FlowDocument = {
  format: "agentstudio.flow";
  format_version: 1;
  name: string;
  description: string;
  tags: string[];
  graph: GraphDocument;
  exported_at?: string | null;
  source_version?: number | null;
};

// ---------------------------------------------------------------------------------------
// Runs
// ---------------------------------------------------------------------------------------

export type RunError = { code: string; message: string; node_id?: string; [key: string]: unknown };

export type Run = {
  id: string;
  flow_id: string;
  flow_name: string;
  version: number;
  version_label: string;
  status: RunStatus;
  trigger: RunTrigger;
  inputs: Record<string, unknown>;
  outputs: Record<string, unknown> | null;
  error: RunError | null;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  cost_simulated: boolean;
  step_count: number;
  triggered_by: string | null;
  rerun_of_id: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
};

export type StepEvent = { type: string; [key: string]: unknown };

export type Step = {
  id: string;
  node_id: string;
  node_type: string;
  label: string;
  iteration: string;
  seq: number;
  status: StepStatus;
  attempt: number;
  input: Record<string, unknown> | null;
  output: unknown;
  error: RunError | null;
  events: StepEvent[];
  handles: string[];
  model: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  cached: boolean;
  continued: boolean;
  started_at: string;
  finished_at: string | null;
  latency_ms: number | null;
};

export type Approval = {
  id: string;
  run_id: string;
  flow_id: string;
  flow_name: string;
  node_id: string;
  title: string;
  message: string;
  context: Record<string, unknown>;
  status: ApprovalStatus;
  run_status: RunStatus;
  expires_at: string | null;
  decided_by_name: string | null;
  decided_at: string | null;
  comment: string;
  created_at: string;
};

export type RunDetail = Run & { graph: GraphDocument; steps: Step[]; approvals: Approval[] };

// ---------------------------------------------------------------------------------------
// Knowledge, catalog, dashboard
// ---------------------------------------------------------------------------------------

export type KnowledgeBase = {
  id: string;
  name: string;
  description: string;
  document_count: number;
  chunk_count: number;
  created_at: string;
  updated_at: string;
};

export type KnowledgeDocument = {
  id: string;
  knowledge_base_id: string;
  title: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  chunk_count: number;
  token_count: number;
  created_at: string;
};

export type SearchHit = {
  chunk_id: string;
  document_id: string;
  title: string;
  heading: string;
  text: string;
  snippet: string;
  score: number;
};

export type SearchResult = { results: SearchHit[]; context: string };

export type InputField = {
  name: string;
  type: "string" | "number" | "integer" | "boolean" | "object" | "array";
  description?: string;
  required?: boolean;
  default?: unknown;
};

export type Template = {
  slug: string;
  name: string;
  description: string;
  category: string;
  tags: string[];
  node_types: string[];
  node_count: number;
  inputs: InputField[];
  sample: Record<string, unknown>;
  requires_knowledge: string[];
  graph: GraphDocument;
};

export type Model = {
  ref: string;
  provider: string;
  model: string;
  label: string;
  offline: boolean;
  price_input: number;
  price_output: number;
  simulated: boolean;
};

export type DashboardDay = { date: string; succeeded: number; failed: number; other: number };

export type TopFlow = {
  flow_id: string;
  name: string;
  runs: number;
  success_rate: number;
  cost_usd: number;
};

export type Dashboard = {
  period_days: number;
  runs: number;
  succeeded: number;
  failed: number;
  waiting: number;
  running: number;
  success_rate: number | null;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  p50_ms: number | null;
  p95_ms: number | null;
  pending_approvals: number;
  flows: number;
  published_flows: number;
  daily: DashboardDay[];
  top_flows: TopFlow[];
  recent_runs: Run[];
};
