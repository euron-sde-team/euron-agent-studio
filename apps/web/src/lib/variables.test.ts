import { describe, expect, it } from "vitest";

import type { GraphDocument, GraphNode } from "@/lib/types";
import { partialReference, variablesFor } from "@/lib/variables";

const node = (id: string, type: string, config: Record<string, unknown> = {}): GraphNode => ({
  id,
  type,
  position: { x: 0, y: 0 },
  label: "",
  config,
  settings: {},
});

const GRAPH: GraphDocument = {
  schema_version: 1,
  nodes: [
    node("start", "start", { inputs: [{ name: "subject", description: "Ticket subject" }] }),
    node("classify", "llm", {
      output_mode: "json",
      json_fields: [{ name: "category", description: "billing or technical" }],
    }),
    node("each", "loop"),
    node("lookup", "http", { parameters: [{ name: "email" }] }),
    node("agent", "agent"),
  ],
  edges: [
    { id: "a", source: "start", source_handle: "out", target: "classify", target_handle: "in" },
    { id: "b", source: "classify", source_handle: "out", target: "each", target_handle: "in" },
    { id: "c", source: "each", source_handle: "body", target: "agent", target_handle: "in" },
    { id: "d", source: "lookup", source_handle: "tool", target: "agent", target_handle: "tools" },
  ],
};

describe("variablesFor", () => {
  it("offers inputs, upstream outputs, loop values and secrets", () => {
    const paths = variablesFor(GRAPH, "agent", ["CRM_TOKEN"]).map((v) => v.path);
    expect(paths).toContain("inputs.subject");
    expect(paths).toContain("classify.json.category");
    expect(paths).not.toContain("classify.json");
    expect(paths).toContain("item");
    expect(paths).toContain("each.results");
    expect(paths).toContain("secrets.CRM_TOKEN");
  });

  it("offers tool arguments to a tool lent to an agent", () => {
    const paths = variablesFor(GRAPH, "lookup").map((v) => v.path);
    expect(paths).toContain("args.email");
  });
});

describe("partialReference", () => {
  it("finds the reference being typed", () => {
    expect(partialReference("Hello {{inputs.su", 17)).toEqual({ start: 6, query: "inputs.su" });
    expect(partialReference("Hello {{inputs.subject}} and", 28)).toBeNull();
    expect(partialReference("no braces", 4)).toBeNull();
  });
});
