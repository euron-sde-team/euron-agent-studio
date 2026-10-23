import { ancestors, enclosingLoops } from "@/lib/graph";
import { definitionOf } from "@/lib/nodes";
import type { GraphDocument } from "@/lib/types";

/** Something a template can read, offered by the variable picker as `{{path}}`. */
export type Variable = { path: string; group: string; description: string };

type Field = { name?: unknown; description?: unknown };

function fields(value: unknown): { name: string; description: string }[] {
  if (!Array.isArray(value)) return [];
  return (value as Field[])
    .filter((f) => typeof f.name === "string" && f.name)
    .map((f) => ({ name: String(f.name), description: String(f.description ?? "") }));
}

/** Every value the templates of node `nodeId` can read, nearest first within each group. */
export function variablesFor(
  graph: GraphDocument,
  nodeId: string,
  secretNames: string[] = [],
): Variable[] {
  const found: Variable[] = [];
  const start = graph.nodes.find((n) => n.type === "start");
  for (const input of fields(start?.config.inputs)) {
    found.push({
      path: `inputs.${input.name}`,
      group: "Inputs",
      description: input.description || "A run input",
    });
  }
  const loops = enclosingLoops(graph, nodeId);
  if (loops.length) {
    found.push({ path: "item", group: "Loop", description: "The current item" });
    found.push({ path: "index", group: "Loop", description: "Its position, from 0" });
    for (const loop of loops.slice(0, -1)) {
      found.push({ path: `${loop}.item`, group: "Loop", description: `The item of ${loop}` });
    }
  }
  const node = graph.nodes.find((n) => n.id === nodeId);
  const lentTo = graph.edges.filter((e) => e.source === nodeId && e.target_handle === "tools");
  if (node && lentTo.length) {
    const params =
      node.type === "http"
        ? fields(node.config.parameters).map((p) => p.name)
        : node.type === "knowledge"
          ? ["query"]
          : node.type === "calculator"
            ? ["expression"]
            : node.type === "json_transform"
              ? ["input"]
              : [];
    for (const param of params) {
      found.push({
        path: `args.${param}`,
        group: "Tool arguments",
        description: "Filled in by the agent when it calls this tool",
      });
    }
  }
  const upstream = ancestors(graph, nodeId);
  for (const other of graph.nodes) {
    if (!upstream.has(other.id) || other.type === "start" || other.type === "note") continue;
    const definition = definitionOf(other.type);
    for (const output of definition?.outputs ?? []) {
      if (output.path === "json") {
        const jsonFields = fields(other.config.json_fields);
        if (other.config.output_mode !== "json") continue;
        for (const field of jsonFields) {
          found.push({
            path: `${other.id}.json.${field.name}`,
            group: other.label || other.id,
            description: field.description || "A structured field",
          });
        }
        continue;
      }
      found.push({
        path: `${other.id}.${output.path}`,
        group: other.label || other.id,
        description: output.description,
      });
    }
  }
  for (const name of secretNames) {
    found.push({
      path: `secrets.${name}`,
      group: "Secrets",
      description: "Resolved at run time, masked in traces",
    });
  }
  return found;
}

/** The `{{...}}` reference the user is typing at `caret`, if any: "inputs.su" in "{{inputs.su". */
export function partialReference(
  text: string,
  caret: number,
): { start: number; query: string } | null {
  const before = text.slice(0, caret);
  const open = before.lastIndexOf("{{");
  if (open === -1 || before.lastIndexOf("}}") > open) return null;
  const query = before.slice(open + 2).trimStart();
  if (!/^[\w.]*$/.test(query)) return null;
  return { start: open, query };
}
