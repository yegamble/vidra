# Observability spec — vidra-user (Next.js + TypeScript frontend)

> Authoritative spec for logging and OpenTelemetry in `vidra-user`. Apply it from
> the first scaffolding slice — observability is part of the definition of done,
> not a later phase. Mirrors `vidra-core/.ralph/specs/observability.md`; the two
> are designed to correlate (shared trace context across the API boundary).

## Goals

1. **Developer-friendly** — server and client behavior is observable without a
   debugger: one structured logger, leveled, correlated by a request/correlation
   ID and (when enabled) a trace ID. Readable locally, JSON in production.
2. **Security-friendly** — logs, spans, analytics, URLs, and error reports never
   leak secrets, access/refresh tokens, session cookies, message plaintext, or
   unnecessary PII. This holds on the client too (browser console, error
   trackers, breadcrumbs).

---

## 1. Logging

### One logger, no stray console
- Provide a single structured logger module (e.g. `lib/logger`). Server code
  (route handlers, server actions, middleware, RSC) logs structured JSON; client
  code logs sparingly through the same module's browser-safe path.
- Raw `console.log`/`console.error`/`console.warn` are **banned in committed
  source** (the logger may use them internally). Enforced by ESLint `no-console`
  (error), with a narrow allow-list only inside the logger module.
- Levels configurable (`debug|info|warn|error`); default `info` (prod JSON,
  dev pretty). Never log at `debug` in production by default.

### Field conventions
- Structured key/value, never string-interpolated values. Reuse stable keys:
  `request_id`, `correlation_id`, `trace_id`, `route`, `status`, `latency_ms`,
  `error_code`. Bind the request/correlation ID once per request and thread it
  into every server log for that request.

### Security-friendly logging (hard rules)
Never log / never send to an error tracker / never put in a URL or analytics
event / never put in a span attribute:
- Access or refresh tokens, session cookies, `Authorization` headers, passwords,
  OAuth secrets, TOTP codes, API keys.
- **Encrypted-messaging plaintext** — keep it out of logs, analytics, URLs,
  server traces, breadcrumbs, and test snapshots (matches `.ralph/PROMPT.md`).
- PII beyond need (raw email, full message bodies). Prefer IDs.
- A redaction helper in the logger module strips a denylist of sensitive keys
  from any logged object; do not log whole request/response or config objects.
- Do not persist long-lived secrets in `localStorage`; prefer the backend's
  secure-cookie/session approach. Token values never appear in any log line.

---

## 2. OpenTelemetry

### Scope
- Instrument with the OpenTelemetry JS SDK via Next.js `instrumentation.ts`
  (e.g. `@vercel/otel` or the OTel Node SDK). Disabled by default; opt-in via env
  so dev and CI pay zero cost.
- Config (`.env.example`, all server-side / non-`NEXT_PUBLIC_` unless required):
  - `OTEL_ENABLED` — default `false`.
  - `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_PROTOCOL`.
  - `OTEL_SERVICE_NAME` — default `vidra-user`.
- Browser/RUM tracing is **optional and opt-in**; if enabled it must respect the
  security rules above (no tokens/PII in span attributes).

### Trace propagation to the backend (the correlation contract)
- Every server-side fetch to `vidra-core` must **inject the W3C `traceparent`
  (and `tracestate`) header** so a frontend request and its backend handling
  share one trace. `vidra-core` is configured to accept inbound `traceparent`
  (see its observability spec). This is what lets the database-effect
  verification flow line up a UI action with the exact backend log/DB change.
- When OTel is disabled, still send an `X-Correlation-ID` header (the per-request
  correlation ID) on every call to `vidra-core` so logs correlate without full
  tracing. `vidra-core` accepts/echoes this exact header name (see its spec) —
  keep the two in lock-step.

### Logs ↔ traces
- When OTel is enabled, server log lines include `trace_id`/`span_id` from the
  active span.

---

## 3. Enforcement (PLANNED — fix_plan P1.5; not yet built)

> ⚠️ STATUS: the frontend is not scaffolded yet — there is no `package.json`,
> `npm run ci`, ESLint config, or `frontend-ci.yml` job running. The items below
> are the build target (fix_plan P1.5), not checks that run today. Build them as
> the app is scaffolded; until then these rules are honor-system.

- **ESLint `no-console`** (error) — to be wired into `npm run lint`, which is part
  of the canonical `npm run ci` gate, so stray console logging fails CI.
- A **secrets-in-logs / token-in-storage check** (lint rule or a small test/grep)
  — to fail when a denylisted key is logged or a token is written to `localStorage`.
- **Trace-propagation test** — an integration/e2e test to assert server-side calls
  to `vidra-core` carry `X-Correlation-ID` (and `traceparent` when OTel is on).
- **Local↔CI parity** — `frontend-ci.yml` runs the same `npm run ci` gate
  developers run locally (typecheck + lint + unit + build + Playwright smoke);
  `ci-guard.yml` enforces that it invokes the canonical gate and hides no
  failures. A feature is not done on a local pass alone — branch CI must be green.
- **Release gate** (fix_plan P15): logger in place with redaction; ESLint
  `no-console` enforced; no secrets/PII/plaintext in logs, analytics, URLs, or
  traces; OTel + `traceparent` propagation to `vidra-core` working (or behind a
  documented flag).

See `.ralph/PROMPT.md` (Frontend security; encrypted-messaging plaintext rule)
and `vidra-core/.ralph/specs/observability.md` (the matching backend contract).
