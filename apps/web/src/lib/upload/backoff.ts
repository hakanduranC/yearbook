/** min(30 s, 1 s · 2^attempt) plus up to 1 s of jitter. */
export function backoffMs(attempt: number, random: () => number = Math.random): number {
  const base = Math.min(30_000, 1000 * 2 ** Math.max(0, attempt))
  return base + Math.floor(random() * 1000)
}
