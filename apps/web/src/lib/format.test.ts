import { describe, expect, it } from "vitest";

import {
  formatBytes,
  formatCost,
  formatDuration,
  formatRelative,
  initials,
  slugify,
} from "@/lib/format";

describe("format", () => {
  it("formats durations from milliseconds to hours", () => {
    expect(formatDuration(null)).toBe("-");
    expect(formatDuration(320)).toBe("320 ms");
    expect(formatDuration(1530)).toBe("1.5 s");
    expect(formatDuration(42_000)).toBe("42 s");
    expect(formatDuration(125_000)).toBe("2 min 5 s");
    expect(formatDuration(3_900_000)).toBe("1 h 5 min");
  });

  it("shows tiny costs with enough digits to compare runs", () => {
    expect(formatCost(0)).toBe("$0");
    expect(formatCost(0.00002)).toBe("<$0.0001");
    expect(formatCost(0.000224)).toBe("$0.0002");
    expect(formatCost(1.234)).toBe("$1.23");
    expect(formatCost(1234.5)).toBe("$1,235");
  });

  it("formats sizes, names and relative times", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(initials("Ava Martin")).toBe("AM");
    expect(initials("  ")).toBe("?");
    const now = new Date("2026-10-23T12:00:00Z");
    expect(formatRelative("2026-10-23T11:00:00Z", now)).toBe("1 hour ago");
    expect(formatRelative("2026-10-23T11:59:50Z", now)).toBe("just now");
  });

  it("makes file-name-safe slugs", () => {
    expect(slugify("Support triage!")).toBe("support-triage");
    expect(slugify("???")).toBe("flow");
  });
});
