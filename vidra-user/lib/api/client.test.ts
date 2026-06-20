import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiRequest } from "./client";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("apiRequest", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("calls the configured base URL and attaches a correlation id (no auth by default)", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));
    await apiRequest("/api/v1/instance");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8080/api/v1/instance");
    const headers = init.headers as Record<string, string>;
    expect(headers["x-correlation-id"]).toMatch(/^[0-9a-f-]{36}$/);
    expect(headers.authorization).toBeUndefined();
  });

  it("sends a bearer token and JSON body when provided", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));
    await apiRequest("/x", { method: "POST", token: "secret", body: { a: 1 } });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers.authorization).toBe("Bearer secret");
    expect(headers["content-type"]).toBe("application/json");
    expect(init.body).toBe(JSON.stringify({ a: 1 }));
    expect(init.method).toBe("POST");
  });

  it("builds query strings and omits undefined params", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));
    await apiRequest("/api/v1/videos", {
      query: { sort: "popular", limit: 5, offset: undefined },
    });
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toBe("http://localhost:8080/api/v1/videos?sort=popular&limit=5");
  });

  it("returns the parsed body on success", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ name: "Vidra" }));
    const out = await apiRequest<{ name: string }>("/api/v1/instance");
    expect(out.name).toBe("Vidra");
  });

  it("maps the error envelope to ApiError", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        { error: { code: "not_found", message: "video not found", request_id: "r1" } },
        404,
      ),
    );
    await expect(apiRequest("/api/v1/videos/x")).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
      code: "not_found",
      message: "video not found",
      requestId: "r1",
    });
  });

  it("falls back to a generic ApiError for a non-envelope error body", async () => {
    fetchMock.mockResolvedValue(new Response("oops", { status: 500 }));
    const err = (await apiRequest("/x").catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(500);
    expect(err.code).toBe("http_error");
  });

  it("returns undefined on 204", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    const out = await apiRequest("/x", { method: "DELETE" });
    expect(out).toBeUndefined();
  });

  it("wraps network failures as a network_error ApiError", async () => {
    fetchMock.mockRejectedValue(new TypeError("fetch failed"));
    const err = (await apiRequest("/x").catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe("network_error");
    expect(err.status).toBe(0);
  });
});
