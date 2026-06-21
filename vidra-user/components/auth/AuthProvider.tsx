"use client";

import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { authApi, setAccessToken } from "@/lib/api";
import type {
  AuthResponse,
  LoginRequest,
  RegisterRequest,
  UpdateProfileRequest,
  User,
} from "@/lib/api";

type SessionStatus = "anon" | "authed";

interface SessionContextValue {
  user: User | null;
  status: SessionStatus;
  login: (credentials: LoginRequest) => Promise<void>;
  register: (input: RegisterRequest) => Promise<void>;
  updateProfile: (input: UpdateProfileRequest) => Promise<void>;
  deactivate: (password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

// AuthProvider holds the session client-side: the access token lives in the
// in-memory auth-store (auto-attached by the API client), the refresh token +
// user live in React state. Nothing is persisted, so a reload signs out until
// refresh-token rehydration lands.
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [refreshToken, setRefreshToken] = useState<string | null>(null);

  const apply = useCallback((res: AuthResponse) => {
    setAccessToken(res.token);
    setRefreshToken(res.refresh_token);
    setUser(res.user);
  }, []);

  const login = useCallback(
    async (credentials: LoginRequest) => {
      apply(await authApi.login(credentials));
    },
    [apply],
  );

  const register = useCallback(
    async (input: RegisterRequest) => {
      apply(await authApi.register(input));
    },
    [apply],
  );

  const updateProfile = useCallback(async (input: UpdateProfileRequest) => {
    setUser(await authApi.updateMe(input));
  }, []);

  const deactivate = useCallback(async (password: string) => {
    await authApi.deactivate(password);
    // The backend already revoked every session; drop the local one too.
    setAccessToken(null);
    setRefreshToken(null);
    setUser(null);
  }, []);

  const logout = useCallback(async () => {
    const rt = refreshToken;
    setAccessToken(null);
    setRefreshToken(null);
    setUser(null);
    if (rt) {
      try {
        await authApi.logout(rt);
      } catch {
        // Best-effort revoke; logout is idempotent server-side.
      }
    }
  }, [refreshToken]);

  const value = useMemo<SessionContextValue>(
    () => ({
      user,
      status: user ? "authed" : "anon",
      login,
      register,
      updateProfile,
      deactivate,
      logout,
    }),
    [user, login, register, updateProfile, deactivate, logout],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const ctx = useContext(SessionContext);
  if (!ctx) {
    throw new Error("useSession must be used within <AuthProvider>");
  }
  return ctx;
}
