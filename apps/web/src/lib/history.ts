/**
 * Undo and redo for the editor: snapshots of the graph, bounded so a long session does not
 * grow without limit. Pure data, so it is easy to test and cannot drift from the canvas.
 */
export type History<T> = { past: T[]; future: T[] };

export const HISTORY_LIMIT = 100;

export function emptyHistory<T>(): History<T> {
  return { past: [], future: [] };
}

/** Record the state before a change; a new change clears what could be redone. */
export function record<T>(history: History<T>, before: T, limit = HISTORY_LIMIT): History<T> {
  const past = [...history.past, before];
  return { past: past.length > limit ? past.slice(past.length - limit) : past, future: [] };
}

export function undo<T>(history: History<T>, current: T): { history: History<T>; state: T } | null {
  const previous = history.past.at(-1);
  if (previous === undefined) return null;
  return {
    history: { past: history.past.slice(0, -1), future: [current, ...history.future] },
    state: previous,
  };
}

export function redo<T>(history: History<T>, current: T): { history: History<T>; state: T } | null {
  const [next, ...rest] = history.future;
  if (next === undefined) return null;
  return { history: { past: [...history.past, current], future: rest }, state: next };
}
