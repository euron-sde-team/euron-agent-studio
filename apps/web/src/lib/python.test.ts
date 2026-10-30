import { describe, expect, it } from "vitest";

import { pythonLiteral } from "@/lib/python";

describe("pythonLiteral", () => {
  it("writes JSON values as Python literals", () => {
    expect(pythonLiteral({ ok: true, missing: null, off: false, n: 2.5 })).toBe(
      '{"ok": True, "missing": None, "off": False, "n": 2.5}',
    );
    expect(pythonLiteral([1, "two", [null]])).toBe('[1, "two", [None]]');
  });

  it("keeps strings escaped the way Python reads them", () => {
    expect(pythonLiteral('say "hi"\nthen go \\ home')).toBe('"say \\"hi\\"\\nthen go \\\\ home"');
    expect(pythonLiteral({ 'a"b': "c" })).toBe('{"a\\"b": "c"}');
  });

  it("never emits JSON-only words", () => {
    expect(pythonLiteral(undefined)).toBe("None");
    expect(pythonLiteral(Number.NaN)).toBe("None");
  });
});
