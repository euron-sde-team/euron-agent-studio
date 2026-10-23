import { describe, expect, it } from "vitest";

import {
  NODE_TYPES,
  defaultConfig,
  handleLabel,
  nextNodeId,
  outputHandles,
  type NodeType,
} from "@/lib/nodes";

describe("node catalog", () => {
  it("covers every node type the engine runs", () => {
    expect(NODE_TYPES.map((d) => d.type).sort()).toEqual(
      [
        "agent",
        "approval",
        "calculator",
        "condition",
        "http",
        "json_transform",
        "knowledge",
        "llm",
        "loop",
        "note",
        "output",
        "start",
      ].sort(),
    );
  });

  it("derives handles like the engine does", () => {
    expect(outputHandles({ type: "llm", config: {} })).toEqual(["out"]);
    expect(outputHandles({ type: "http", config: {} })).toEqual(["out", "tool"]);
    expect(outputHandles({ type: "loop", config: {} })).toEqual(["body", "done"]);
    expect(outputHandles({ type: "approval", config: {} })).toEqual(["approved", "rejected"]);
    expect(outputHandles({ type: "output", config: {} })).toEqual([]);
    const condition = {
      type: "condition",
      config: {
        routes: [
          { id: "urgent", label: "Urgent" },
          { id: "vip", label: "VIP" },
        ],
      },
    };
    expect(outputHandles(condition)).toEqual(["route_urgent", "route_vip", "else"]);
    expect(handleLabel(condition, "route_vip")).toBe("VIP");
    expect(handleLabel(condition, "else")).toBe("Else");
  });

  it("gives new nodes readable unique ids that avoid reserved names", () => {
    expect(nextNodeId("llm", [])).toBe("prompt");
    expect(nextNodeId("llm", ["prompt", "prompt_2"])).toBe("prompt_3");
    expect(nextNodeId("loop", [])).toBe("for_each");
    expect(nextNodeId("http", ["http_request"])).toBe("http_request_2");
  });

  it("starts every type with a config the inspector can edit", () => {
    for (const definition of NODE_TYPES) {
      const config = defaultConfig(definition.type as NodeType, "offline");
      expect(config).toBeTypeOf("object");
    }
    expect(defaultConfig("llm", "openai/gpt-4o-mini").model).toBe("openai/gpt-4o-mini");
    expect(defaultConfig("condition").routes).toHaveLength(1);
  });
});
