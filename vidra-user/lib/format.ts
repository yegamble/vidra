// Small pure formatting helpers for UI display. Pure + dependency-free so they
// unit-test in the node environment.

/** formatCount renders a view/follower count compactly: 942, 1.2K, 3.4M, 1.0B. */
export function formatCount(n: number): string {
  if (!Number.isFinite(n) || n < 0) return "0";
  if (n < 1000) return String(Math.floor(n));
  const units = [
    { v: 1_000_000_000, s: "B" },
    { v: 1_000_000, s: "M" },
    { v: 1_000, s: "K" },
  ];
  for (const { v, s } of units) {
    if (n >= v) {
      const scaled = n / v;
      // One decimal, but drop a trailing .0 (1.0K -> 1K).
      const text = scaled >= 100 ? String(Math.floor(scaled)) : scaled.toFixed(1).replace(/\.0$/, "");
      return `${text}${s}`;
    }
  }
  return String(Math.floor(n));
}

/** relativeTime renders an ISO timestamp as a coarse "x ago" relative to now. */
export function relativeTime(iso: string, now: Date = new Date()): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const secs = Math.floor((now.getTime() - then) / 1000);
  if (secs < 0) return "just now";
  const steps: Array<{ limit: number; div: number; unit: string }> = [
    { limit: 60, div: 1, unit: "s" },
    { limit: 3600, div: 60, unit: "m" },
    { limit: 86400, div: 3600, unit: "h" },
    { limit: 604800, div: 86400, unit: "d" },
    { limit: 2629800, div: 604800, unit: "w" },
    { limit: 31557600, div: 2629800, unit: "mo" },
  ];
  for (const { limit, div, unit } of steps) {
    if (secs < limit) {
      const value = Math.floor(secs / div);
      if (unit === "s" && value < 5) return "just now";
      return `${value}${unit} ago`;
    }
  }
  return `${Math.floor(secs / 31557600)}y ago`;
}
