import { apiBaseUrl } from "@/lib/config";
import { logger } from "@/lib/logger";

import type { ApiErrorEnvelope, FieldError } from "./types";

/**
 * ApiError is thrown for any non-2xx response. It carries the backend's stable
 * error `code`, the HTTP `status`, the correlating `request_id`, and field-level
 * validation problems (on 422). Callers branch on `code`/`status`.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId?: string;
  readonly fields?: FieldError[];

  constructor(args: {
    status: number;
    code: string;
    message: string;
    requestId?: string;
    fields?: FieldError[];
  }) {
    super(args.message);
    this.name = "ApiError";
    this.status = args.status;
    this.code = args.code;
    this.requestId = args.requestId;
    this.fields = args.fields;
  }
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  query?: Record<string, string | number | boolean | undefined>;
  body?: unknown;
  /** Bearer token for authenticated calls. Never logged. */
  token?: string;
  signal?: AbortSignal;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = new URL(apiBaseUrl + path);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined) {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url.toString();
}

async function toApiError(res: Response): Promise<ApiError> {
  let code = "http_error";
  let message = `request failed with status ${res.status}`;
  let requestId: string | undefined;
  let fields: FieldError[] | undefined;
  try {
    const body = (await res.json()) as Partial<ApiErrorEnvelope>;
    if (body.error) {
      code = body.error.code || code;
      message = body.error.message || message;
      requestId = body.error.request_id;
      fields = body.error.fields;
    }
  } catch {
    // Non-JSON or empty body — keep the generic message.
  }
  return new ApiError({ status: res.status, code, message, requestId, fields });
}

/**
 * apiRequest performs a typed JSON call to vidra-core. It attaches an
 * X-Correlation-ID (so frontend and backend logs line up; W3C traceparent is
 * added with the OTel slice), maps the error envelope to ApiError, and returns
 * the parsed body. The Authorization header and token are never logged.
 */
export async function apiRequest<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const method = opts.method ?? "GET";
  const url = buildUrl(path, opts.query);
  const correlationId = crypto.randomUUID();

  const headers: Record<string, string> = {
    accept: "application/json",
    "x-correlation-id": correlationId,
  };
  if (opts.body !== undefined) {
    headers["content-type"] = "application/json";
  }
  if (opts.token) {
    headers.authorization = `Bearer ${opts.token}`;
  }

  let res: Response;
  try {
    res = await fetch(url, {
      method,
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: opts.signal,
    });
  } catch (cause) {
    logger.error("api request network error", {
      method,
      path,
      correlation_id: correlationId,
      error: cause instanceof Error ? cause.message : String(cause),
    });
    throw new ApiError({
      status: 0,
      code: "network_error",
      message: "could not reach the server",
    });
  }

  if (!res.ok) {
    const err = await toApiError(res);
    logger.warn("api request failed", {
      method,
      path,
      status: err.status,
      error_code: err.code,
      correlation_id: correlationId,
      request_id: err.requestId,
    });
    throw err;
  }

  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}
