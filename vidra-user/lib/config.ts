// Typed runtime configuration. Read environment once here so the rest of the app
// imports typed values instead of touching process.env directly.

function trimTrailingSlash(url: string): string {
  return url.replace(/\/+$/, "");
}

// Base URL of the vidra-core API. NEXT_PUBLIC_ is inlined at build time and
// exposed to the browser, so it must be a non-secret URL only.
export const apiBaseUrl: string = trimTrailingSlash(
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8080",
);

// OpenTelemetry is opt-in and zero-cost when off. The OTel SDK / traceparent
// propagation is wired in a later slice; until then calls still carry an
// X-Correlation-ID for log correlation.
export const otelEnabled: boolean = process.env.OTEL_ENABLED === "true";
