import { describe, expect, it } from "vitest";

import { highlightParts } from "@/lib/highlight";

describe("highlightParts", () => {
  it("splits marked terms out of a snippet", () => {
    expect(highlightParts("The **meal** allowance is **60 EUR**.")).toEqual([
      { text: "The ", mark: false },
      { text: "meal", mark: true },
      { text: " allowance is ", mark: false },
      { text: "60 EUR", mark: true },
      { text: ".", mark: false },
    ]);
    expect(highlightParts("no marks")).toEqual([{ text: "no marks", mark: false }]);
  });
});
