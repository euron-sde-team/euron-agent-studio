import { Graph, layout as dagreLayout } from "@dagrejs/dagre";
import type { Edge, Node } from "@xyflow/react";

import { definitionOf, outputHandles } from "@/lib/nodes";
import type { GraphDocument, GraphEdge, GraphNode, StepStatus } from "@/lib/types";

export type CanvasNodeData = {
  node: GraphNode;
  errors: number;
  warnings: number;
  runStatus?: StepStatus;
  /** Loop iterations seen for this node in the current run (for "3 runs" badges). */
  runCount?: number;
};

export type CanvasNode = Node<CanvasNodeData, "flow" | "note">;
export type CanvasEdge = Edge;

/** Rough node sizes for layout before the canvas has measured them. */
export const NODE_WIDTH = 248;
export const NODE_HEIGHT = 76;

export function edgeId(source: string, sourceHandle: string, target: string, targetHandle: string) {
  return `e_${source}_${sourceHandle}_${target}_${targetHandle}`;
}

export function toCanvasNode(node: GraphNode): CanvasNode {
  return {
    id: node.id,
    type: node.type === "note" ? "note" : "flow",
    position: { x: node.position.x, y: node.position.y },
    data: { node, errors: 0, warnings: 0 },
    // Notes sit behind the flow so they never hide a handle.
    zIndex: node.type === "note" ? -1 : 0,
  };
}

export function toCanvasEdge(edge: GraphEdge): CanvasEdge {
  const tool = edge.target_handle === "tools";
  return {
    id: edge.id,
    source: edge.source,
    target: edge.target,
    sourceHandle: edge.source_handle,
    targetHandle: edge.target_handle,
    className: tool ? "as-tool-edge" : undefined,
  };
}

export function toCanvas(graph: GraphDocument): { nodes: CanvasNode[]; edges: CanvasEdge[] } {
  return { nodes: graph.nodes.map(toCanvasNode), edges: graph.edges.map(toCanvasEdge) };
}

export function toGraph(
  nodes: CanvasNode[],
  edges: CanvasEdge[],
  viewport?: GraphDocument["viewport"],
): GraphDocument {
  return {
    schema_version: 1,
    nodes: nodes.map((canvas) => ({
      ...canvas.data.node,
      position: { x: Math.round(canvas.position.x), y: Math.round(canvas.position.y) },
    })),
    edges: edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      source_handle: edge.sourceHandle ?? "out",
      target: edge.target,
      target_handle: edge.targetHandle ?? "in",
    })),
    viewport: viewport ?? null,
  };
}

export type ConnectionCheck = { ok: true } | { ok: false; reason: string };

/** Whether a connection makes sense before the server sees it, and why not. */
export function checkConnection(
  source: GraphNode | undefined,
  target: GraphNode | undefined,
  sourceHandle: string | null | undefined,
  targetHandle: string | null | undefined,
  edges: Pick<CanvasEdge, "source" | "target" | "sourceHandle" | "targetHandle">[],
): ConnectionCheck {
  if (!source || !target) return { ok: false, reason: "Unknown node." };
  if (source.id === target.id) return { ok: false, reason: "A node cannot connect to itself." };
  const sourceDef = definitionOf(source.type);
  const targetDef = definitionOf(target.type);
  if (!sourceDef || !targetDef) return { ok: false, reason: "Unknown node type." };
  const fromHandle = sourceHandle ?? "out";
  const toHandle = targetHandle ?? "in";
  if (!outputHandles(source).includes(fromHandle))
    return { ok: false, reason: "That output does not exist." };
  if (!targetDef.inputs.includes(toHandle))
    return { ok: false, reason: `${targetDef.label} has no ${toHandle} input.` };
  if (toHandle === "tools" && fromHandle !== "tool")
    return { ok: false, reason: "Connect a tool's As a tool output to an agent's Tools." };
  if (fromHandle === "tool" && toHandle !== "tools")
    return { ok: false, reason: "As a tool only connects to an agent's Tools input." };
  const duplicate = edges.some(
    (edge) =>
      edge.source === source.id &&
      edge.target === target.id &&
      (edge.sourceHandle ?? "out") === fromHandle &&
      (edge.targetHandle ?? "in") === toHandle,
  );
  if (duplicate) return { ok: false, reason: "Those two are already connected." };
  return { ok: true };
}

/**
 * A clean left-to-right layout with dagre. Tool edges are left out of the ranking (a tool
 * sits below the agent that uses it, not in the flow of control) and notes keep their place.
 */
export function autoLayout(
  nodes: CanvasNode[],
  edges: CanvasEdge[],
  measured: (id: string) => { width: number; height: number } | undefined = () => undefined,
): CanvasNode[] {
  const graph = new Graph();
  graph.setGraph({ rankdir: "LR", nodesep: 48, ranksep: 96, marginx: 24, marginy: 24 });
  graph.setDefaultEdgeLabel(() => ({}));
  const flowNodes = nodes.filter((n) => n.data.node.type !== "note");
  for (const node of flowNodes) {
    const size = measured(node.id) ?? { width: NODE_WIDTH, height: NODE_HEIGHT };
    graph.setNode(node.id, { width: size.width, height: size.height });
  }
  const toolOf = new Map<string, string>();
  for (const edge of edges) {
    if (edge.targetHandle === "tools") {
      toolOf.set(edge.source, edge.target);
      continue;
    }
    if (graph.hasNode(edge.source) && graph.hasNode(edge.target))
      graph.setEdge(edge.source, edge.target);
  }
  // Tools are ranked by their agent, then placed under it.
  for (const tool of toolOf.keys()) {
    if (graph.hasNode(tool) && !edges.some((e) => e.source === tool && e.targetHandle !== "tools"))
      graph.removeNode(tool);
  }
  dagreLayout(graph);
  const placed = new Map<string, { x: number; y: number }>();
  for (const id of graph.nodes()) {
    const point = graph.node(id) as { x: number; y: number; width: number; height: number };
    placed.set(id, { x: point.x - point.width / 2, y: point.y - point.height / 2 });
  }
  const toolsByAgent = new Map<string, string[]>();
  for (const [tool, agent] of toolOf) {
    if (placed.has(tool)) continue;
    toolsByAgent.set(agent, [...(toolsByAgent.get(agent) ?? []), tool]);
  }
  for (const [agent, tools] of toolsByAgent) {
    const anchor = placed.get(agent);
    if (!anchor) continue;
    const width = NODE_WIDTH + 24;
    const start = anchor.x - ((tools.length - 1) * width) / 2;
    tools.forEach((tool, index) =>
      placed.set(tool, { x: start + index * width, y: anchor.y + NODE_HEIGHT + 110 }),
    );
  }
  return nodes.map((node) => {
    const position = placed.get(node.id);
    return position ? { ...node, position } : node;
  });
}

/** Ids of every node upstream of `id` through flow edges (what its templates can read). */
export function ancestors(graph: Pick<GraphDocument, "edges">, id: string): Set<string> {
  const incoming = new Map<string, string[]>();
  for (const edge of graph.edges) {
    if (edge.target_handle === "tools") continue;
    incoming.set(edge.target, [...(incoming.get(edge.target) ?? []), edge.source]);
  }
  const seen = new Set<string>();
  const stack = [...(incoming.get(id) ?? [])];
  while (stack.length) {
    const next = stack.pop()!;
    if (seen.has(next)) continue;
    seen.add(next);
    stack.push(...(incoming.get(next) ?? []));
  }
  return seen;
}

/** Loops whose body contains `id` (reachable from their `body` handle), innermost last. */
export function enclosingLoops(graph: Pick<GraphDocument, "nodes" | "edges">, id: string) {
  const loops: string[] = [];
  for (const node of graph.nodes) {
    if (node.type !== "loop") continue;
    const stack = graph.edges
      .filter((e) => e.source === node.id && e.source_handle === "body")
      .map((e) => e.target);
    const seen = new Set<string>();
    while (stack.length) {
      const next = stack.pop()!;
      if (seen.has(next) || next === node.id) continue;
      seen.add(next);
      stack.push(
        ...graph.edges
          .filter((e) => e.source === next && e.target_handle !== "tools")
          .map((e) => e.target),
      );
    }
    if (seen.has(id)) loops.push(node.id);
  }
  return loops;
}
