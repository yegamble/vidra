// In-memory access-token holder so apiRequest can attach the bearer token
// automatically. The token is NEVER persisted to localStorage (per the security
// spec) and is lost on reload until refresh-token rehydration lands in a later
// slice. The value never appears in any log line.
let accessToken: string | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}
