import { apiRequest } from "./client";
import type {
  AuthResponse,
  LoginRequest,
  PasswordResetConfirmRequest,
  PasswordResetRequest,
  RegisterRequest,
  UpdateProfileRequest,
  User,
} from "./types";

/** Typed wrappers for the vidra-core auth endpoints. */
export const authApi = {
  /** POST /api/v1/auth/register — create an account; returns a session. */
  register: (body: RegisterRequest) =>
    apiRequest<AuthResponse>("/api/v1/auth/register", { method: "POST", body }),

  /** POST /api/v1/auth/login — exchange credentials for a session. */
  login: (body: LoginRequest) =>
    apiRequest<AuthResponse>("/api/v1/auth/login", { method: "POST", body }),

  /**
   * POST /api/v1/auth/password-reset — start the reset flow. Always 202
   * (enumeration-safe): a matching active account is mailed a reset token
   * out-of-band; the response never reveals whether the email exists.
   */
  requestPasswordReset: (body: PasswordResetRequest) =>
    apiRequest<void>("/api/v1/auth/password-reset", { method: "POST", body }),

  /**
   * POST /api/v1/auth/password-reset/confirm — set a new password using the
   * single-use token from the reset message. 204 on success (all the account's
   * sessions are revoked server-side); 400 if the token is invalid/used/expired.
   */
  confirmPasswordReset: (body: PasswordResetConfirmRequest) =>
    apiRequest<void>("/api/v1/auth/password-reset/confirm", { method: "POST", body }),

  /** POST /api/v1/auth/logout — revoke a session (idempotent, always 204). */
  logout: (refreshToken: string) =>
    apiRequest<void>("/api/v1/auth/logout", {
      method: "POST",
      body: { refresh_token: refreshToken },
    }),

  /** GET /api/v1/auth/me — the current account (uses the stored bearer token). */
  me: () => apiRequest<User>("/api/v1/auth/me"),

  /** PATCH /api/v1/auth/me — update the current account's profile; returns it. */
  updateMe: (body: UpdateProfileRequest) =>
    apiRequest<User>("/api/v1/auth/me", { method: "PATCH", body }),

  /**
   * POST /api/v1/auth/me/deactivate — disable the current account after
   * confirming its password. Revokes all sessions server-side (204).
   */
  deactivate: (password: string) =>
    apiRequest<void>("/api/v1/auth/me/deactivate", {
      method: "POST",
      body: { password },
    }),
};
