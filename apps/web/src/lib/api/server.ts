
/**
 * Server-only FastAPI transport.
 * Never import this file from a client component.
 */

import type { ApiErrorCode, ApiErrorResponse } from "./contracts";

const DEFAULT_TIMEOUT_MS = 120_000;

type AllowedEndpoint = "/api/v1/ready" | "/api/v1/verify";

type BackendResult =
  | { ok: true; status: 200; data: unknown }
  | { ok: false; status: number; error: ApiErrorResponse };

function failure(
  status: number,
  code: ApiErrorCode,
  message: string,
  details?: unknown,
): BackendResult {
  return {
    ok: false,
    status,
    error:
      details === undefined
        ? { code, message }
        : { code, message, details },
  };
}

function backendEndpoint(path: AllowedEndpoint): URL | null {
  const configured = process.env.API_BASE_URL?.trim();

  if (!configured) {
    return null;
  }

  try {
    const base = new URL(configured);

    if (
      !["http:", "https:"].includes(base.protocol) ||
      // Private credentials must not travel over plain HTTP
      // when the application is running in production.
      (process.env.NODE_ENV === "production" &&
        base.protocol !== "https:") ||
      base.username ||
      base.password ||
      base.search ||
      base.hash
    ) {
      return null;
    }

    return new URL(path, base.origin);
  } catch {
    return null;
  }
}

export async function requestBackend(
  path: AllowedEndpoint,
  options: {
    method: "GET" | "POST";
    body?: unknown;
    timeoutMs?: number;
    verifiedUserId?: string;
  },
): Promise<BackendResult> {
  const url = backendEndpoint(path);

  if (!url) {
    return failure(
      503,
      "BACKEND_NOT_CONFIGURED",
      "The backend service is not configured.",
    );
  }

  // Private server-to-server credential.
  // Never expose this token to the browser.
  const token = process.env.INTERNAL_API_TOKEN?.trim();

  if (
    process.env.NODE_ENV === "production" &&
    path === "/api/v1/verify" &&
    (!token || token.length < 32 || !options.verifiedUserId)
  ) {
    return failure(
      503,
      "BACKEND_NOT_CONFIGURED",
      "The verification service is not configured.",
    );
  }

  try {
    const headers: Record<string, string> = {};

    if (options.method === "POST") {
      headers["Content-Type"] = "application/json";
    }

    if (token && path === "/api/v1/verify") {
      headers["X-Service-Token"] = token;
    }

    // Use only the server-verified authentication identity.
    if (options.verifiedUserId && path === "/api/v1/verify") {
      headers["X-Verified-User"] = options.verifiedUserId;
    }

    const response = await fetch(url, {
      method: options.method,
      headers,

      // Never forward private credentials through redirects.
      redirect: "error",

      body:
        options.method === "POST"
          ? JSON.stringify(options.body)
          : undefined,

      cache: "no-store",

      signal: AbortSignal.timeout(
        options.timeoutMs ?? DEFAULT_TIMEOUT_MS,
      ),
    });

    let data: unknown;

    try {
      data = await response.json();
    } catch {
      return failure(
        502,
        "INVALID_BACKEND_RESPONSE",
        "The backend returned invalid JSON.",
      );
    }

    if (!response.ok) {
      // Preserve existing validation error behavior.
      if (response.status === 422) {
        const details =
          typeof data === "object" &&
          data !== null &&
          "detail" in data
            ? data.detail
            : undefined;

        return failure(
          422,
          "BACKEND_REJECTED_REQUEST",
          "The backend rejected the submitted data.",
          details,
        );
      }

      // A busy verification worker or an enforced request limit.
      // Preserve HTTP 429 rather than treating it as a crash.
      if (response.status === 429) {
        return failure(
          429,
          "BACKEND_ERROR",
          "The AI verification engine is busy or temporarily limiting requests. Please wait a moment and try again.",
        );
      }

      // Infrastructure or inference service unavailable.
      if (response.status === 503) {
        return failure(
          503,
          "BACKEND_ERROR",
          "The backend could not complete the request.",
        );
      }

      // All other unexpected upstream failures.
      return failure(
        502,
        "BACKEND_ERROR",
        "The backend could not complete the request.",
      );
    }

    return {
      ok: true,
      status: 200,
      data,
    };
  } catch (error: unknown) {
    if (
      error instanceof Error &&
      (error.name === "TimeoutError" ||
        error.name === "AbortError")
    ) {
      return failure(
        504,
        "BACKEND_TIMEOUT",
        "The backend request timed out.",
      );
    }

    return failure(
      503,
      "BACKEND_UNAVAILABLE",
      "The backend service is unavailable.",
    );
  }
}
