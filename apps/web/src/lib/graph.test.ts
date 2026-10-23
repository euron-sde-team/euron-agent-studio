import { describe, expect, it } from "vitest";

import {
  ancestors,
  autoLayout,
  checkConnection,
  enclosingLoops,
  toCanvas,
  toGraph,
} from "@/lib/graph";
import type { GraphDocument, GraphNode } from "@/lib/types";

const node = (id: string, type: string, config: Record<string, unknown> = {}): GraphNode => ({
  id,
  type,
  position: { x: 0, y: 0 },
  label: "",
  config,
  settings: {},
});

const edge = (source: string, target: string, sourceHandle = "out", targetHandle = "in") => ({
  id: `${source}-${target}-${sourceHandle}`,
  source,
  source_handle: sourceHandle,
  target,
  target_handle: targetHandle,
});

const GRAPH: GraphDocument = {
  schema_version: 1,
  nodes: [
    node("start", "start"),
    node("classify", "llm"),
    node("route", "condition", { routes: [{ id: "urgent", label: "Urgent" }] }),
    node("agent", "agent"),
    node("search", "knowledge"),
    node("each", "loop"),
    node("task", "http"),
    node("result", "output"),
  ],
  edges: [
    edge("start", "classify"),
    edge("classify", "route"),
    edge("route", "agent", "route_urgent"),
    edge("search", "agent", "tool", "tools"),
    edge("agent", "each"),
    edge("each", "task", "body"),
    edge("each", "result", "done"),
  ],
};

describe("graph conversion", () => {
  it("round-trips the document through the canvas", () => {
    const canvas = toCanvas(GRAPH);
    expect(canvas.edges.find((e) => e.targetHandle === "tools")?.className).toBe("as-tool-edge");
    const back = toGraph(canvas.nodes, canvas.edges);
    expect(back.nodes.map((n) => n.id)).toEqual(GRAPH.nodes.map((n) => n.id));
    expect(back.edges).toEqual(GRAPH.edges);
  });
});

describe("checkConnection", () => {
  const find = (id: string) => GRAPH.nodes.find((n) => n.id === id);
  const edges = toCanvas(GRAPH).edges;

  it("accepts flow edges and tools wired to an agent", () => {
    expect(checkConnection(find("classify"), find("result"), "out", "in", edges).ok).toBe(true);
    expect(checkConnection(find("task"), find("agent"), "tool", "tools", edges).ok).toBe(true);
  });

  it("explains what does not make sense", () => {
    const self = checkConnection(find("classify"), find("classify"), "out", "in", edges);
    expect(self).toEqual({ ok: false, reason: "A node cannot connect to itself." });
    expect(checkConnection(find("classify"), find("start"), "out", "in", edges).ok).toBe(false);
    expect(checkConnection(find("classify"), find("agent"), "out", "tools", edges).ok).toBe(false);
    expect(checkConnection(find("task"), find("result"), "tool", "in", edges).ok).toBe(false);
    expect(checkConnection(find("start"), find("classify"), "out", "in", edges)).toEqual({
      ok: false,
      reason: "Those two are already connected.",
    });
  });
});

describe("graph structure", () => {
  it("finds what a node can read and which loops contain it", () => {
    expect([...ancestors(GRAPH, "agent")].sort()).toEqual(["classify", "route", "start"]);
    expect(enclosingLoops(GRAPH, "task")).toEqual(["each"]);
    expect(enclosingLoops(GRAPH, "result")).toEqual([]);
  });

  it("lays the flow out left to right with tools under their agent", () => {
    const { nodes, edges } = toCanvas(GRAPH);
    const placed = new Map(autoLayout(nodes, edges).map((n) => [n.id, n.position]));
    expect(placed.get("start")!.x).toBeLessThan(placed.get("classify")!.x);
    expect(placed.get("classify")!.x).toBeLessThan(placed.get("route")!.x);
    expect(placed.get("search")!.y).toBeGreaterThan(placed.get("agent")!.y);
  });
});
