/** Split a search snippet with **marks** into plain and highlighted parts. */
export function highlightParts(snippet: string): { text: string; mark: boolean }[] {
  const parts: { text: string; mark: boolean }[] = [];
  const pattern = /\*\*(.+?)\*\*/g;
  let last = 0;
  for (const match of snippet.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > last) parts.push({ text: snippet.slice(last, index), mark: false });
    parts.push({ text: match[1] ?? "", mark: true });
    last = index + match[0].length;
  }
  if (last < snippet.length) parts.push({ text: snippet.slice(last), mark: false });
  return parts;
}
