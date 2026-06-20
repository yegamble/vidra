import { describe, expect, it } from "vitest";

import { redact } from "./logger";

describe("redact", () => {
  it("redacts sensitive keys (case-insensitive, nested)", () => {
    const input = {
      username: "ada",
      password: "hunter2",
      Authorization: "Bearer abc.def",
      nested: { apiKey: "k", token: "t", keep: 1 },
      list: [{ session: "s" }, { ok: true }],
    };
    const out = redact(input) as Record<string, unknown>;
    expect(out.username).toBe("ada");
    expect(out.password).toBe("[REDACTED]");
    expect(out.Authorization).toBe("[REDACTED]");
    const nested = out.nested as Record<string, unknown>;
    expect(nested.apiKey).toBe("[REDACTED]");
    expect(nested.token).toBe("[REDACTED]");
    expect(nested.keep).toBe(1);
    const list = out.list as Array<Record<string, unknown>>;
    expect(list[0].session).toBe("[REDACTED]");
    expect(list[1].ok).toBe(true);
  });

  it("passes primitives through unchanged", () => {
    expect(redact("hello")).toBe("hello");
    expect(redact(42)).toBe(42);
    expect(redact(null)).toBeNull();
  });

  it("handles circular references", () => {
    const a: Record<string, unknown> = { name: "a" };
    a.self = a;
    const out = redact(a) as Record<string, unknown>;
    expect(out.name).toBe("a");
    expect(out.self).toBe("[Circular]");
  });
});
