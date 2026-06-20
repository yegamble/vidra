// The single structured logger for vidra-user. All app code logs through this
// module; raw console.* is banned elsewhere by ESLint (no-console). See
// .ralph/specs/observability.md.
//
// Goals: developer-friendly (one leveled, structured logger; JSON in production,
// readable in dev) and security-friendly (a redaction denylist strips secrets,
// tokens, and obvious PII before anything is written).

export type LogLevel = "debug" | "info" | "warn" | "error";

const LEVELS: Record<LogLevel, number> = { debug: 10, info: 20, warn: 30, error: 40 };

// Keys whose values must never be logged (case-insensitive substring match).
const SENSITIVE_KEY_PATTERNS = [
  "password",
  "token",
  "authorization",
  "cookie",
  "secret",
  "apikey",
  "api_key",
  "session",
  "totp",
  "otp",
  "privatekey",
  "private_key",
];

const REDACTED = "[REDACTED]";

function isSensitiveKey(key: string): boolean {
  const k = key.toLowerCase();
  return SENSITIVE_KEY_PATTERNS.some((p) => k.includes(p));
}

/**
 * redact returns a deep copy of value with sensitive fields replaced by
 * "[REDACTED]". Exported so callers (and tests) can sanitise objects before they
 * reach any sink (logs, error trackers, analytics). Cyclic references are
 * collapsed to "[Circular]".
 */
export function redact(value: unknown, seen: WeakSet<object> = new WeakSet()): unknown {
  if (value === null || typeof value !== "object") {
    return value;
  }
  if (seen.has(value as object)) {
    return "[Circular]";
  }
  seen.add(value as object);

  if (Array.isArray(value)) {
    return value.map((v) => redact(v, seen));
  }
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
    out[k] = isSensitiveKey(k) ? REDACTED : redact(v, seen);
  }
  return out;
}

function currentLevel(): LogLevel {
  const raw = (process.env.LOG_LEVEL ?? "").toLowerCase();
  return raw in LEVELS ? (raw as LogLevel) : "info";
}

function isProd(): boolean {
  return process.env.NODE_ENV === "production";
}

type Fields = Record<string, unknown>;

function emit(level: LogLevel, message: string, fields?: Fields): void {
  if (LEVELS[level] < LEVELS[currentLevel()]) {
    return;
  }
  const record = {
    level,
    msg: message,
    time: new Date().toISOString(),
    ...(fields ? (redact(fields) as Fields) : {}),
  };
  // This module is the one place console.* is permitted (see eslint override).
  const line = isProd() ? JSON.stringify(record) : prettyLine(record);
  // eslint-disable-next-line no-console
  const sink = level === "error" ? console.error : level === "warn" ? console.warn : console.log;
  sink(line);
}

function prettyLine(record: Record<string, unknown>): string {
  const { level, msg, time, ...rest } = record;
  const extra = Object.keys(rest).length ? " " + JSON.stringify(rest) : "";
  return `${String(time)} ${String(level).toUpperCase()} ${String(msg)}${extra}`;
}

export const logger = {
  debug: (message: string, fields?: Fields) => emit("debug", message, fields),
  info: (message: string, fields?: Fields) => emit("info", message, fields),
  warn: (message: string, fields?: Fields) => emit("warn", message, fields),
  error: (message: string, fields?: Fields) => emit("error", message, fields),
};
