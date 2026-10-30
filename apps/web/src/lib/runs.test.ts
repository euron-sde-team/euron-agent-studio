import { describe, expect, it } from "vitest";

import { fromStep, mergeSteps, timeline } from "@/lib/runs";
import type { Step } from "@/lib/types";

const step = (patch: Partial<Step>): Step => ({
  id: "s",
  node_id: "classify",
  node_type: "llm",
  label: "Classify",
  iteration: "",
  seq: 1,
  status: "succeeded",
  attempt: 1,
  input: {},
  output: { text: "billing" },
  error: null,
  events: [],
  handles: ["out"],
  model: "offline",
  prompt_tokens: 120,
  completion_tokens: 30,
  cost_usd: 0.0001,
  cached: false,
  continued: false,
  started_at: "2026-10-23T10:00:00.000Z",
  finished_at: "2026-10-23T10:00:00.500Z",
  latency_ms: 500,
  ...patch,
});

describe("runs", () => {
  it("keys stored steps like live ones", () => {
    expect(fromStep(step({ iteration: "2", node_id: "search" })).key).toBe("search#2");
    expect(fromStep(step({})).key).toBe("classify");
  });

  it("lays live steps over stored ones in execution order", () => {
    const stored = [fromStep(step({ seq: 2, status: "running", latency_ms: null }))];
    const live = [{ ...stored[0]!, status: "succeeded" as const, latencyMs: 640 }];
    const merged = mergeSteps(stored, live);
    expect(merged).toHaveLength(1);
    expect(merged[0]!.status).toBe("succeeded");
    expect(merged[0]!.latencyMs).toBe(640);
  });

  it("places steps on one time axis", () => {
    const steps = [
      fromStep(step({ seq: 1 })),
      fromStep(
        step({
          seq: 2,
          node_id: "draft",
          latency_ms: 1000,
          started_at: "2026-10-23T10:00:00.500Z",
        }),
      ),
    ];
    const { rows, spanMs } = timeline(steps, "2026-10-23T10:00:00.000Z", Date.now());
    expect(spanMs).toBe(1500);
    expect(rows[1]!.offset).toBeCloseTo(1 / 3);
    expect(rows[1]!.width).toBeCloseTo(2 / 3);
  });
});
