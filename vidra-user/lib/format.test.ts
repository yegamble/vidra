import { describe, expect, it } from "vitest";

import { formatCount, relativeTime } from "./format";

describe("formatCount", () => {
  it("formats small, thousands, millions, billions", () => {
    expect(formatCount(0)).toBe("0");
    expect(formatCount(942)).toBe("942");
    expect(formatCount(1000)).toBe("1K");
    expect(formatCount(1200)).toBe("1.2K");
    expect(formatCount(15500)).toBe("15.5K");
    expect(formatCount(120000)).toBe("120K");
    expect(formatCount(3_400_000)).toBe("3.4M");
    expect(formatCount(1_000_000_000)).toBe("1B");
  });

  it("guards against negatives / NaN", () => {
    expect(formatCount(-5)).toBe("0");
    expect(formatCount(Number.NaN)).toBe("0");
  });
});

describe("relativeTime", () => {
  const now = new Date("2026-06-20T12:00:00Z");
  const ago = (secs: number) => new Date(now.getTime() - secs * 1000).toISOString();

  it("renders coarse buckets", () => {
    expect(relativeTime(ago(2), now)).toBe("just now");
    expect(relativeTime(ago(45), now)).toBe("45s ago");
    expect(relativeTime(ago(120), now)).toBe("2m ago");
    expect(relativeTime(ago(7200), now)).toBe("2h ago");
    expect(relativeTime(ago(2 * 86400), now)).toBe("2d ago");
    expect(relativeTime(ago(3 * 604800), now)).toBe("3w ago");
    expect(relativeTime(ago(2 * 2629800), now)).toBe("2mo ago");
    expect(relativeTime(ago(2 * 31557600), now)).toBe("2y ago");
  });

  it("handles future and invalid input", () => {
    expect(relativeTime(ago(-30), now)).toBe("just now");
    expect(relativeTime("not-a-date", now)).toBe("");
  });
});
