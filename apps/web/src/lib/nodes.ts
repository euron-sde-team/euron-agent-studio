/**
 * The node catalog: what the canvas offers, which handles each type has and what a new node
 * starts with. It mirrors NODE_SPECS in apps/api/src/agentstudio/engine/graph.py; the API
 * validates every graph, so a drift here shows up as an inline issue, never as a bad run.
 */
import type { GraphNode } from "@/lib/types";

export type NodeType =
  | "start"
  | "llm"
  | "agent"
  | "http"
  | "knowledge"
  | "calculator"
  | "json_transform"
  | "condition"
  | "loop"
  | "approval"
  | "output"
  | "note";

export type NodeCategory = "io" | "ai" | "tool" | "logic" | "human" | "canvas";

export type NodeDefinition = {
  type: NodeType;
  label: string;
  description: string;
  category: NodeCategory;
  /** Target handles: "in" for the flow of control, "tools" for an agent's tools. */
  inputs: string[];
  tool: boolean;
  usesModel: boolean;
  executable: boolean;
  defaultTimeout: number;
  /** The first id a new node of this type gets ("prompt", then "prompt_2", ...). */
  idBase: string;
  /** What other nodes can read from this one, as `{{id.path}}`. */
  outputs: { path: string; description: string }[];
};

export const NODE_TYPES: NodeDefinition[] = [
  {
    type: "start",
    label: "Start",
    description: "The inputs a run starts with",
    category: "io",
    inputs: [],
    tool: false,
    usesModel: false,
    executable: true,
    defaultTimeout: 10,
    idBase: "start",
    outputs: [],
  },
  {
    type: "llm",
    label: "Prompt",
    description: "One model call: text or structured JSON",
    category: "ai",
    inputs: ["in"],
    tool: false,
    usesModel: true,
    executable: true,
    defaultTimeout: 60,
    idBase: "prompt",
    outputs: [
      { path: "text", description: "The model's answer" },
      { path: "json", description: "The parsed fields (JSON output mode)" },
    ],
  },
  {
    type: "agent",
    label: "Agent",
    description: "A model that calls the tools wired to it, in a bounded loop",
    category: "ai",
    inputs: ["in", "tools"],
    tool: false,
    usesModel: true,
    executable: true,
    defaultTimeout: 180,
    idBase: "agent",
    outputs: [
      { path: "text", description: "The final answer" },
      { path: "json", description: "The parsed fields (JSON output mode)" },
      { path: "tool_calls", description: "Every tool call with its arguments and result" },
      { path: "iterations", description: "How many model rounds it took" },
    ],
  },
  {
    type: "http",
    label: "HTTP request",
    description: "Call an API; also usable as an agent tool",
    category: "tool",
    inputs: ["in"],
    tool: true,
    usesModel: false,
    executable: true,
    defaultTimeout: 30,
    idBase: "http_request",
    outputs: [
      { path: "status", description: "The HTTP status code" },
      { path: "ok", description: "True for a 2xx status" },
      { path: "json", description: "The response body as JSON" },
      { path: "text", description: "The body as text (text responses)" },
    ],
  },
  {
    type: "knowledge",
    label: "Knowledge search",
    description: "Full-text search over a knowledge base",
    category: "tool",
    inputs: ["in"],
    tool: true,
    usesModel: false,
    executable: true,
    defaultTimeout: 20,
    idBase: "search",
    outputs: [
      { path: "context", description: "Numbered sources, ready for a prompt" },
      { path: "results", description: "Each passage with its title and score" },
    ],
  },
  {
    type: "calculator",
    label: "Calculator",
    description: "Safe arithmetic: + - * / ** % and round, min, max",
    category: "tool",
    inputs: ["in"],
    tool: true,
    usesModel: false,
    executable: true,
    defaultTimeout: 5,
    idBase: "calculate",
    outputs: [{ path: "result", description: "The number" }],
  },
  {
    type: "json_transform",
    label: "JSON transform",
    description: "Reshape data with a JMESPath expression",
    category: "tool",
    inputs: ["in"],
    tool: true,
    usesModel: false,
    executable: true,
    defaultTimeout: 5,
    idBase: "transform",
    outputs: [{ path: "result", description: "The transformed value" }],
  },
  {
    type: "condition",
    label: "Condition",
    description: "Route to the first branch whose rules match",
    category: "logic",
    inputs: ["in"],
    tool: false,
    usesModel: false,
    executable: true,
    defaultTimeout: 5,
    idBase: "condition",
    outputs: [
      { path: "route", description: "The id of the branch taken" },
      { path: "label", description: "Its label" },
    ],
  },
  {
    type: "loop",
    label: "Loop",
    description: "Run the body once per item of a list",
    category: "logic",
    inputs: ["in"],
    tool: false,
    usesModel: false,
    executable: true,
    defaultTimeout: 600,
    idBase: "for_each",
    outputs: [
      { path: "results", description: "One collected value per item" },
      { path: "count", description: "How many items there were" },
      { path: "failed", description: "How many items failed" },
    ],
  },
  {
    type: "approval",
    label: "Human approval",
    description: "Pause the run until someone approves or rejects",
    category: "human",
    inputs: ["in"],
    tool: false,
    usesModel: false,
    executable: true,
    defaultTimeout: 10,
    idBase: "approval",
    outputs: [
      { path: "decision", description: "approved or rejected" },
      { path: "comment", description: "What the reviewer wrote" },
      { path: "decided_by", description: "Who decided" },
    ],
  },
  {
    type: "output",
    label: "Output",
    description: "The run's result, as named fields",
    category: "io",
    inputs: ["in"],
    tool: false,
    usesModel: false,
    executable: true,
    defaultTimeout: 5,
    idBase: "output",
    outputs: [],
  },
  {
    type: "note",
    label: "Note",
    description: "A sticky note for whoever reads the flow next",
    category: "canvas",
    inputs: [],
    tool: false,
    usesModel: false,
    executable: false,
    defaultTimeout: 1,
    idBase: "note",
    outputs: [],
  },
];

export const NODE_BY_TYPE = new Map(NODE_TYPES.map((d) => [d.type, d]));

export function definitionOf(type: string): NodeDefinition | undefined {
  return NODE_BY_TYPE.get(type as NodeType);
}

/** Names the template language already uses; a node id cannot take them. */
export const RESERVED_IDS = new Set(["inputs", "secrets", "item", "index", "args", "run", "loop"]);
export const NODE_ID_PATTERN = /^[a-z][a-z0-9_]{0,39}$/;

type Route = { id: string; label: string };

/** Source handles of a node: conditions derive theirs from their routes. */
export function outputHandles(node: Pick<GraphNode, "type" | "config">): string[] {
  switch (node.type) {
    case "condition": {
      const routes = Array.isArray(node.config.routes) ? (node.config.routes as Route[]) : [];
      return [...routes.map((r) => `route_${r.id}`), "else"];
    }
    case "loop":
      return ["body", "done"];
    case "approval":
      return ["approved", "rejected"];
    case "output":
    case "note":
      return [];
    case "http":
    case "knowledge":
    case "calculator":
    case "json_transform":
      return ["out", "tool"];
    default:
      return ["out"];
  }
}

export function handleLabel(node: Pick<GraphNode, "type" | "config">, handle: string): string {
  if (handle.startsWith("route_") && node.type === "condition") {
    const routes = Array.isArray(node.config.routes) ? (node.config.routes as Route[]) : [];
    return routes.find((r) => `route_${r.id}` === handle)?.label || handle.slice(6);
  }
  const labels: Record<string, string> = {
    out: "Next",
    tool: "As a tool",
    else: "Else",
    body: "Each item",
    done: "Done",
    approved: "Approved",
    rejected: "Rejected",
    in: "In",
    tools: "Tools",
  };
  return labels[handle] ?? handle.replace(/_/g, " ");
}

/** The configuration a new node starts with. */
export function defaultConfig(type: NodeType, model = "offline"): Record<string, unknown> {
  switch (type) {
    case "start":
      return {
        inputs: [{ name: "input", type: "string", description: "", required: true }],
        sample: {},
      };
    case "llm":
      return {
        model,
        system: "",
        prompt: "",
        temperature: 0.2,
        max_tokens: 800,
        output_mode: "text",
        json_fields: [],
      };
    case "agent":
      return {
        model,
        system: "",
        task: "",
        temperature: 0.2,
        max_tokens: 800,
        max_iterations: 5,
        output_mode: "text",
        json_fields: [],
      };
    case "http":
      return {
        method: "GET",
        url: "",
        headers: [],
        query: [],
        body_mode: "none",
        body: "",
        expect: "json",
        fail_on_status: true,
        parameters: [],
        tool_name: null,
        tool_description: "",
      };
    case "knowledge":
      return { knowledge_base_id: "", query: "", top_k: 4, tool_name: null, tool_description: "" };
    case "calculator":
      return { expression: "", tool_name: null, tool_description: "" };
    case "json_transform":
      return { input: "", expression: "", tool_name: null, tool_description: "" };
    case "condition":
      return {
        routes: [
          {
            id: "yes",
            label: "Yes",
            match: "all",
            rules: [{ left: "", operator: "equals", right: "" }],
          },
        ],
      };
    case "loop":
      return {
        items: "",
        max_items: 50,
        concurrency: 1,
        collect: "",
        continue_on_item_error: false,
      };
    case "approval":
      return { title: "Review required", message: "", expires_after_hours: null };
    case "output":
      return { fields: [{ name: "result", value: "" }] };
    case "note":
      return { text: "", color: "yellow" };
  }
}

/** A readable, unique id for a new node: prompt, prompt_2, ... */
export function nextNodeId(type: NodeType, taken: Iterable<string>): string {
  const base = definitionOf(type)?.idBase ?? "node";
  const used = new Set(taken);
  if (!used.has(base) && !RESERVED_IDS.has(base)) return base;
  for (let index = 2; ; index += 1) {
    const candidate = `${base}_${index}`;
    if (!used.has(candidate)) return candidate;
  }
}

/** A node's display name: its label, or the type's name. */
export function displayLabel(node: Pick<GraphNode, "type" | "label">): string {
  return node.label || definitionOf(node.type)?.label || node.type;
}

export const OPERATORS: { value: string; label: string; unary?: boolean }[] = [
  { value: "equals", label: "equals" },
  { value: "not_equals", label: "does not equal" },
  { value: "contains", label: "contains" },
  { value: "not_contains", label: "does not contain" },
  { value: "starts_with", label: "starts with" },
  { value: "ends_with", label: "ends with" },
  { value: "greater_than", label: "is greater than" },
  { value: "greater_or_equal", label: "is at least" },
  { value: "less_than", label: "is less than" },
  { value: "less_or_equal", label: "is at most" },
  { value: "is_empty", label: "is empty", unary: true },
  { value: "is_not_empty", label: "is not empty", unary: true },
  { value: "in_list", label: "is one of (comma separated)" },
  { value: "matches", label: "matches the pattern" },
];

export const FIELD_TYPES = ["string", "number", "integer", "boolean", "object", "array"] as const;
