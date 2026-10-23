/**
 * A run's live trace, folded from its server-sent events. Pure: the same events always give
 * the same state, so the hook that feeds it can reconnect and replay without double counting.
 */
import type { RunError, RunStatus, StepStatus } from "@/lib/types";

export type TraceStep = {
  key: string;
  nodeId: string;
  nodeType: string;
  label: string;
  iteration: string;
  seq: number;
  status: StepStatus;
  attempt: number;
  input: unknown;
  output: unknown;
  error: RunError | null;
  handles: string[];
  model: string | null;
  promptTokens: number;
  completionTokens: number;
  costUsd: number;
  cached: boolean;
  latencyMs: number | null;
  events: Record<string, unknown>[];
};

export type TraceState = {
  status: RunStatus;
  steps: TraceStep[];
  outputs: Record<string, unknown> | null;
  error: RunError | null;
  promptTokens: number;
  completionTokens: number;
  costUsd: number;
  durationMs: number | null;
  waitingOn: string[];
  lastEventId: string | null;
};

export type TraceEvent = { id: string | null; type: string; data: Record<string, unknown> };

export function emptyTrace(status: RunStatus = "queued"): TraceState {
  return {
    status,
    steps: [],
    outputs: null,
    error: null,
    promptTokens: 0,
    completionTokens: 0,
    costUsd: 0,
    durationMs: null,
    waitingOn: [],
    lastEventId: null,
  };
}

const num = (value: unknown): number => (typeof value === "number" ? value : 0);
const str = (value: unknown, fallback = ""): string =>
  typeof value === "string" ? value : fallback;

function stepKey(nodeId: string, iteration: string): string {
  return iteration ? `${nodeId}#${iteration}` : nodeId;
}

function upsert(
  steps: TraceStep[],
  key: string,
  patch: (step: TraceStep | undefined) => TraceStep,
) {
  const index = steps.findIndex((s) => s.key === key);
  if (index === -1) return [...steps, patch(undefined)];
  const next = steps.slice();
  next[index] = patch(steps[index]);
  return next;
}

function blank(key: string, data: Record<string, unknown>): TraceStep {
  return {
    key,
    nodeId: str(data.node_id),
    nodeType: str(data.node_type),
    label: str(data.label),
    iteration: str(data.iteration),
    seq: num(data.seq),
    status: "running",
    attempt: num(data.attempt) || 1,
    input: data.input ?? null,
    output: null,
    error: null,
    handles: [],
    model: null,
    promptTokens: 0,
    completionTokens: 0,
    costUsd: 0,
    cached: false,
    latencyMs: null,
    events: [],
  };
}

export function applyEvent(state: TraceState, event: TraceEvent): TraceState {
  const data = event.data;
  const next: TraceState = { ...state, lastEventId: event.id ?? state.lastEventId };
  switch (event.type) {
    case "run.queued":
      return { ...next, status: "queued" };
    case "run.started":
      return { ...next, status: "running", waitingOn: [] };
    case "step.started": {
      const key = stepKey(str(data.node_id), str(data.iteration));
      return {
        ...next,
        steps: upsert(state.steps, key, (step) => ({
          ...(step ?? blank(key, data)),
          status: "running",
          attempt: num(data.attempt) || 1,
          input: data.input ?? step?.input ?? null,
          seq: num(data.seq) || step?.seq || 0,
          label: str(data.label, step?.label ?? ""),
        })),
      };
    }
    case "step.progress": {
      const key = stepKey(str(data.node_id), str(data.iteration));
      const payload = (data.event ?? {}) as Record<string, unknown>;
      return {
        ...next,
        steps: upsert(state.steps, key, (step) => {
          const base = step ?? blank(key, data);
          return { ...base, events: [...base.events, payload] };
        }),
      };
    }
    case "step.finished": {
      const key = stepKey(str(data.node_id), str(data.iteration));
      return {
        ...next,
        steps: upsert(state.steps, key, (step) => ({
          ...(step ?? blank(key, data)),
          nodeType: str(data.node_type, step?.nodeType ?? ""),
          status: str(data.status, "succeeded") as StepStatus,
          attempt: num(data.attempt) || step?.attempt || 1,
          output: data.output ?? null,
          error: (data.error as RunError | null) ?? null,
          handles: Array.isArray(data.handles) ? (data.handles as string[]) : [],
          model: typeof data.model === "string" ? data.model : null,
          promptTokens: num(data.prompt_tokens),
          completionTokens: num(data.completion_tokens),
          costUsd: num(data.cost_usd),
          cached: Boolean(data.cached),
          latencyMs: typeof data.latency_ms === "number" ? data.latency_ms : null,
        })),
      };
    }
    case "step.waiting": {
      const key = stepKey(str(data.node_id), "");
      return {
        ...next,
        steps: upsert(state.steps, key, (step) => ({
          ...(step ?? blank(key, data)),
          status: "waiting",
        })),
      };
    }
    case "run.waiting":
      return {
        ...next,
        status: "waiting",
        waitingOn: Array.isArray(data.waiting_on) ? (data.waiting_on as string[]) : [],
      };
    case "approval.decided":
      return next;
    case "run.finished":
      return {
        ...next,
        status: str(data.status, "succeeded") as RunStatus,
        outputs: (data.outputs as Record<string, unknown> | null) ?? null,
        error: (data.error as RunError | null) ?? null,
        promptTokens: num(data.prompt_tokens) || totals(state).promptTokens,
        completionTokens: num(data.completion_tokens) || totals(state).completionTokens,
        costUsd: num(data.cost_usd) || totals(state).costUsd,
        durationMs: typeof data.duration_ms === "number" ? data.duration_ms : null,
        // A replayed trace may miss running steps that were cut short: they did not finish.
        steps: state.steps.map((s) =>
          s.status === "running" ? { ...s, status: "cancelled" as StepStatus } : s,
        ),
      };
    default:
      return next;
  }
}

export function totals(state: Pick<TraceState, "steps">) {
  let promptTokens = 0;
  let completionTokens = 0;
  let costUsd = 0;
  for (const step of state.steps) {
    promptTokens += step.promptTokens;
    completionTokens += step.completionTokens;
    costUsd += step.costUsd;
  }
  return { promptTokens, completionTokens, costUsd };
}

const PRIORITY: StepStatus[] = [
  "running",
  "waiting",
  "failed",
  "cancelled",
  "succeeded",
  "skipped",
];

/** One status per node for the canvas: the most telling one across its loop iterations. */
export function nodeStatuses(steps: Pick<TraceStep, "nodeId" | "status">[]) {
  const byNode = new Map<string, { status: StepStatus; count: number }>();
  for (const step of steps) {
    const current = byNode.get(step.nodeId);
    if (!current) {
      byNode.set(step.nodeId, { status: step.status, count: 1 });
      continue;
    }
    const status =
      PRIORITY.indexOf(step.status) < PRIORITY.indexOf(current.status)
        ? step.status
        : current.status;
    byNode.set(step.nodeId, { status, count: current.count + 1 });
  }
  return byNode;
}

export const FINAL: RunStatus[] = ["succeeded", "failed", "cancelled"];
