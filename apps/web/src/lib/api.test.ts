import { describe, expect, it } from "vitest";

import { errorFrom } from "@/lib/api";

describe("errorFrom", () => {
  it("reads the server's error envelope", () => {
    const error = errorFrom(409, {
      error: {
        code: "revision_conflict",
        message: "Someone saved first.",
        request_id: "abc",
        details: { current_revision: 4 },
      },
    });
    expect(error.status).toBe(409);
    expect(error.code).toBe("revision_conflict");
    expect(error.message).toBe("Someone saved first.");
    expect(error.requestId).toBe("abc");
    expect(error.details).toEqual({ current_revision: 4 });
  });

  it("falls back to a generic message for bodies without an envelope", () => {
    expect(errorFrom(502, null).code).toBe("server_error");
    expect(errorFrom(404, "nope").code).toBe("request_failed");
  });
});
