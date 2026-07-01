import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getAccessToken, setAccessToken } from "./auth-store";
import { authApi } from "./auth";
import { apiRequest } from "./client";

const session = {
  token: "acc",
  refresh_token: "ref",
  token_type: "Bearer",
  expires_in: 900,
  user: {
    id: "u1",
    username: "ada",
    email: "ada@example.test",
    role: "user",
    email_verified: false,
    display_name: "",
    bio: "",
    created_at: "2026-01-01T00:00:00Z",
  },
};

function okJson(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("authApi + auth-store", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    setAccessToken(null);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    setAccessToken(null);
  });

  it("login POSTs credentials and returns the session", async () => {
    fetchMock.mockResolvedValue(okJson(session));
    const res = await authApi.login({ email: "ada@example.test", password: "pw" });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8080/api/v1/auth/login");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ email: "ada@example.test", password: "pw" }));
    expect(res.token).toBe("acc");
    expect(res.user.username).toBe("ada");
  });

  it("register POSTs to the register endpoint", async () => {
    fetchMock.mockResolvedValue(okJson(session));
    await authApi.register({ username: "ada", email: "ada@example.test", password: "password1" });
    expect((fetchMock.mock.calls[0] as [string])[0]).toBe(
      "http://localhost:8080/api/v1/auth/register",
    );
  });

  it("auto-attaches the stored access token to subsequent calls", async () => {
    setAccessToken("acc");
    fetchMock.mockResolvedValue(okJson(session.user));
    await authApi.me();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8080/api/v1/auth/me");
    expect((init.headers as Record<string, string>).authorization).toBe("Bearer acc");
  });

  it("sends no auth header when no token is stored", async () => {
    fetchMock.mockResolvedValue(okJson({}));
    await apiRequest("/api/v1/instance");
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>).authorization).toBeUndefined();
  });

  it("requestPasswordReset POSTs the email to the reset endpoint", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 202 }));
    await authApi.requestPasswordReset({ email: "ada@example.test" });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8080/api/v1/auth/password-reset");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ email: "ada@example.test" }));
  });

  it("confirmPasswordReset POSTs the token and new password", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await authApi.confirmPasswordReset({ token: "tok-123", password: "newpassword-2" });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8080/api/v1/auth/password-reset/confirm");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ token: "tok-123", password: "newpassword-2" }));
  });

  it("requestEmailVerification POSTs to the verify-email endpoint", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 202 }));
    await authApi.requestEmailVerification();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8080/api/v1/auth/verify-email");
    expect(init.method).toBe("POST");
  });

  it("confirmEmailVerification POSTs the token to the confirm endpoint", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await authApi.confirmEmailVerification({ token: "verify-tok" });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8080/api/v1/auth/verify-email/confirm");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ token: "verify-tok" }));
  });

  it("logout posts the refresh token", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await authApi.logout("ref");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8080/api/v1/auth/logout");
    expect(init.body).toBe(JSON.stringify({ refresh_token: "ref" }));
  });

  it("setAccessToken/getAccessToken round-trip", () => {
    expect(getAccessToken()).toBeNull();
    setAccessToken("x");
    expect(getAccessToken()).toBe("x");
  });
});
