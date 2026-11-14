export function countWritingWords(body: string): number {
  return body.match(/[\p{L}\p{N}]+(?:['’\-][\p{L}\p{N}]+)*/gu)?.length ?? 0;
}

type LineChange = { kind: 'same' | 'added' | 'removed'; text: string };

/** Line comparison with a bounded work budget for essays with many short lines. */
export function compareWriting(previous: string, current: string): LineChange[] | null {
  const a = previous.split('\n');
  const b = current.split('\n');
  if ((a.length + 1) * (b.length + 1) > 250_000) return null;
  const grid = Array.from({ length: a.length + 1 }, () => new Uint16Array(b.length + 1));
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      grid[i][j] = a[i] === b[j] ? grid[i + 1][j + 1] + 1 : Math.max(grid[i + 1][j], grid[i][j + 1]);
    }
  }
  const changes: LineChange[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && a[i] === b[j]) {
      changes.push({ kind: 'same', text: a[i++] });
      j++;
    } else if (i < a.length && (j === b.length || grid[i + 1][j] >= grid[i][j + 1])) {
      changes.push({ kind: 'removed', text: a[i++] });
    } else {
      changes.push({ kind: 'added', text: b[j++] });
    }
  }
  return changes;
}
