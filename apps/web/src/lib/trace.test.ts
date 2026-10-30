import { describe, expect, it } from "vitest";

import { applyEvent, emptyTrace, nodeStatuses, type TraceEvent } from "@/lib/trace";

const events: TraceEvent[] = [
  { id: "1-0", type: "run.queued", data: { status: "queued" } },
  { id: "2-0", type: "run.started", data: { status: "running" } },
  {
    id: "3-0",
    type: "step.started",
    data: { node_id: "search", node_type: "knowledge", iteration: "0", seq: 2, input: { q: "a" } },
  },
  {
    id: "4-0",
    type: "step.started",
    data: { node_id: "search", node_type: "knowledge", iteration: "1", seq: 3 },
  },
  {
    id: "5-0",
    type: "step.finished",
    data: {
      node_id: "search",
      node_type: "knowledge",
      iteration: "0",
      status: "succeeded",
      output: { context: "[1] ..." },
      prompt_tokens: 0,
      latency_ms: 12,
    },
  },
  {
    id: "6-0",
    type: "step.progress",
    data: { node_id: "agent", iteration: "", event: { type: "tool_call", name: "search" } },
  },
];

describe("applyEvent", () => {
  it("folds events into steps keyed by node and iteration", () => {
    const state = events.reduce(applyEvent, emptyTrace());
    expect(state.status).toBe("running");
    expect(state.lastEventId).toBe("6-0");
    const search = state.steps.filter((s) => s.nodeId === "search");
    expect(search.map((s) => [s.iteration, s.status])).toEqual([
      ["0", "succeeded"],
      ["1", "running"],
    ]);
    expect(search[0]!.input).toEqual({ q: "a" });
    expect(search[0]!.latencyMs).toBe(12);
    expect(search[0]!.startedAt).toBe(new Date(3).toISOString());
    expect(state.steps.find((s) => s.nodeId === "agent")!.events).toEqual([
      { type: "tool_call", name: "search" },
    ]);
  });

  it("is idempotent for replayed step events", () => {
    const once = events.reduce(applyEvent, emptyTrace());
    const twice = events.slice(2, 5).reduce(applyEvent, once);
    expect(twice.steps.length).toBe(once.steps.length);
  });

  it("finishes the run and closes steps a replay left open", () => {
    const state = applyEvent(events.reduce(applyEvent, emptyTrace()), {
      id: "7-0",
      type: "run.finished",
      data: { status: "succeeded", outputs: { ok: true }, cost_usd: 0.0004, duration_ms: 900 },
    });
    expect(state.status).toBe("succeeded");
    expect(state.outputs).toEqual({ ok: true });
    expect(state.durationMs).toBe(900);
    expect(state.steps.some((s) => s.status === "running")).toBe(false);
  });

  it("marks a step waiting for a person", () => {
    const state = applyEvent(emptyTrace("running"), {
      id: "9-0",
      type: "step.waiting",
      data: { node_id: "approve", approval_id: "x", title: "Review" },
    });
    expect(state.steps[0]!.status).toBe("waiting");
  });
});

describe("nodeStatuses", () => {
  it("summarises loop iterations with the most telling status", () => {
    const statuses = nodeStatuses([
      { nodeId: "task", status: "succeeded" },
      { nodeId: "task", status: "failed" },
      { nodeId: "task", status: "succeeded" },
      { nodeId: "done", status: "skipped" },
    ]);
    expect(statuses.get("task")).toEqual({ status: "failed", count: 3 });
    expect(statuses.get("done")).toEqual({ status: "skipped", count: 1 });
  });
});
