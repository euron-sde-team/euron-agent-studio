import type { TraceStep } from "@/lib/trace";
import type { Step } from "@/lib/types";

/** A stored step in the same shape as a live one, so one view renders both. */
export function fromStep(step: Step): TraceStep {
  return {
    key: step.iteration ? `${step.node_id}#${step.iteration}` : step.node_id,
    nodeId: step.node_id,
    nodeType: step.node_type,
    label: step.label,
    iteration: step.iteration,
    seq: step.seq,
    status: step.status,
    attempt: step.attempt,
    input: step.input,
    output: step.output,
    error: step.error,
    handles: step.handles,
    model: step.model,
    promptTokens: step.prompt_tokens,
    completionTokens: step.completion_tokens,
    costUsd: step.cost_usd,
    cached: step.cached,
    latencyMs: step.latency_ms,
    events: step.events,
    startedAt: step.started_at,
  };
}

/** Stored steps with the live ones laid over them (the stream is newer while a run moves). */
export function mergeSteps(stored: TraceStep[], live: TraceStep[]): TraceStep[] {
  const byKey = new Map(stored.map((s) => [s.key, s]));
  for (const step of live) {
    const base = byKey.get(step.key);
    byKey.set(
      step.key,
      base
        ? {
            ...base,
            ...step,
            events: step.events.length ? step.events : base.events,
            startedAt: step.startedAt ?? base.startedAt,
          }
        : step,
    );
  }
  return [...byKey.values()].sort((a, b) => a.seq - b.seq);
}

export type TimelineRow = { step: TraceStep; offset: number; width: number };

/** Gantt rows on one time axis from the run's start; running steps extend to `now`. */
export function timeline(
  steps: TraceStep[],
  runStart: string | null,
  now: number,
): { rows: TimelineRow[]; spanMs: number } {
  const started = steps.filter((s) => s.status !== "skipped" && s.startedAt);
  if (!started.length) return { rows: [], spanMs: 0 };
  const origin = Math.min(
    runStart ? new Date(runStart).getTime() : Infinity,
    ...started.map((s) => new Date(s.startedAt!).getTime()),
  );
  const ends = started.map((s) => {
    const begin = new Date(s.startedAt!).getTime();
    return s.latencyMs !== null ? begin + s.latencyMs : now;
  });
  const spanMs = Math.max(1, Math.max(...ends) - origin);
  const rows = started.map((step, index) => {
    const begin = new Date(step.startedAt!).getTime();
    const offset = (begin - origin) / spanMs;
    const width = Math.max(0.006, (ends[index]! - begin) / spanMs);
    return { step, offset, width: Math.min(width, 1 - offset) };
  });
  return { rows, spanMs };
}
