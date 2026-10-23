import { describe, expect, it } from "vitest";

import { ENV_GLOBAL, serializeEnv } from "@/lib/runtime-env";

describe("serializeEnv", () => {
  it("defines the global with defaults and trims trailing slashes", () => {
    const script = serializeEnv({ API_URL: "https://api.example.com/" });
    expect(script.startsWith(`window.${ENV_GLOBAL}=`)).toBe(true);
    expect(script).toContain('"apiUrl":"https://api.example.com"');
    expect(script).toContain('"productName":"Euron AgentStudio"');
  });

  it("keeps the script inert inside HTML", () => {
    const script = serializeEnv({ PRODUCT_NAME: "</script><script>alert(1)</script>" });
    expect(script).not.toContain("</script>");
  });
});
