import { describe, expect, it } from "vitest";

import { emptyHistory, record, redo, undo } from "@/lib/history";

describe("history", () => {
  it("undoes and redoes in order", () => {
    let history = emptyHistory<number>();
    history = record(history, 1);
    history = record(history, 2);
    const first = undo(history, 3)!;
    expect(first.state).toBe(2);
    const second = undo(first.history, first.state)!;
    expect(second.state).toBe(1);
    expect(undo(second.history, second.state)).toBeNull();
    const again = redo(second.history, second.state)!;
    expect(again.state).toBe(2);
  });

  it("forgets what could be redone after a new change", () => {
    let history = record(emptyHistory<string>(), "a");
    const undone = undo(history, "b")!;
    history = record(undone.history, undone.state);
    expect(redo(history, "c")).toBeNull();
  });

  it("is bounded", () => {
    let history = emptyHistory<number>();
    for (let index = 0; index < 150; index += 1) history = record(history, index, 100);
    expect(history.past).toHaveLength(100);
    expect(history.past[0]).toBe(50);
  });
});
