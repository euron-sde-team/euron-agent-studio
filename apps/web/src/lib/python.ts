/**
 * Python source for values shown in copyable snippets. JSON is not Python (`true`, `null`),
 * so a sample input pasted into a script must be rewritten as a Python literal.
 */
export function pythonLiteral(value: unknown): string {
  if (value === null || value === undefined) return "None";
  if (value === true) return "True";
  if (value === false) return "False";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "None";
  // A JSON string is also a valid Python string literal: the escapes are the same.
  if (typeof value === "string") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(pythonLiteral).join(", ")}]`;
  if (typeof value === "object") {
    const items = Object.entries(value as Record<string, unknown>).map(
      ([key, item]) => `${JSON.stringify(key)}: ${pythonLiteral(item)}`,
    );
    return `{${items.join(", ")}}`;
  }
  return "None";
}
