import { describe, expect, it } from "vitest";

import type { WorkspaceSummary } from "@/lib/types";
import { pickWorkspace } from "@/lib/workspace-choice";

const workspace = (slug: string, flows: number): WorkspaceSummary => ({
  id: slug,
  slug,
  name: slug,
  role: "owner",
  flow_count: flows,
  member_count: 1,
});

describe("pickWorkspace", () => {
  const all = [workspace("alpha", 1), workspace("northwind", 8)];

  it("returns to the last workspace when the person still belongs to it", () => {
    expect(pickWorkspace(all, "alpha")).toBe("alpha");
  });

  it("otherwise lands on the busiest workspace", () => {
    expect(pickWorkspace(all, "gone")).toBe("northwind");
    expect(pickWorkspace(all, null)).toBe("northwind");
    expect(pickWorkspace([], null)).toBeNull();
  });
});
