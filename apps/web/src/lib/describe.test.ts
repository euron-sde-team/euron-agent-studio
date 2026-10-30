import { describe, expect, it } from "vitest";

import { describeTrigger, plural } from "@/lib/describe";

describe("describeTrigger", () => {
  it("says who or what started a run", () => {
    expect(describeTrigger({ trigger: "manual", triggered_by: "Leo Chen" })).toBe(
      "Started by Leo Chen",
    );
    expect(describeTrigger({ trigger: "api", triggered_by: "API key Zapier" })).toBe(
      "Started through the API (API key Zapier)",
    );
    expect(describeTrigger({ trigger: "webhook", triggered_by: "Webhook" })).toBe(
      "Started by a signed webhook",
    );
    expect(describeTrigger({ trigger: "rerun", triggered_by: null })).toBe("Re-run");
  });

  it("pluralises counts", () => {
    expect(plural(1, "passage")).toBe("1 passage");
    expect(plural(3, "passage")).toBe("3 passages");
  });
});
