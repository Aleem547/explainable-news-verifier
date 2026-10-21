/**
 * Server-only FastAPI transport.
 * Never import this file from a client component.
 */

import type { ApiErrorCode, ApiErrorResponse } from "./contracts";

const DEFAULT_TIMEOUT_MS = 120_000;

type AllowedEndpoint = "/api/v1/ready" | "/api/v1/verify" | "/api/v1/article/verify";

const isInferencePath = (path: AllowedEndpoint) =>
  path === "/api/v1/verify" || path === "/api/v1/article/verify";

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
    /** The incoming Next.js request signal, if available. */
    signal?: AbortSignal;
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

  // Private server-to-server credential. Never expose it to the browser.
  const token = process.env.INTERNAL_API_TOKEN?.trim();

  if (
    process.env.NODE_ENV === "production" &&
    isInferencePath(path) &&
    (!token || token.length < 32 || !options.verifiedUserId)
  ) {
    return failure(
      503,
      "BACKEND_NOT_CONFIGURED",
      "The verification service is not configured.",
    );
  }

  // A client that already disconnected must not start a new inference request.
  if (options.signal?.aborted) {
    return failure(499, "BACKEND_UNAVAILABLE", "The request was cancelled.");
  }

  // Use a combined AbortController so either the upstream client disconnect
  // OR the local timeout can abort fetch. Clean up the timer and listener.
  const controller = new AbortController();
  let clientCancelled = false;
  let timedOut = false;

  const onClientAbort = () => {
    clientCancelled = true;
    controller.abort();
  };

  options.signal?.addEventListener("abort", onClientAbort, { once: true });

  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const timeoutId = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  try {
    const headers: Record<string, string> = {};

    if (options.method === "POST") {
      headers["Content-Type"] = "application/json";
    }

    if (token && isInferencePath(path)) {
      headers["X-Service-Token"] = token;
    }

    // Use only the server-verified authentication identity.
    if (options.verifiedUserId && isInferencePath(path)) {
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
      signal: controller.signal,
    });

    let data: unknown;

    try {
      data = await response.json();
    } catch (error) {
      // An abort during response-body parsing must still be classified
      // as cancellation or timeout, not an invalid-backend JSON response.
      if (controller.signal.aborted) {
        throw error;
      }
      return failure(
        502,
        "INVALID_BACKEND_RESPONSE",
        "The backend returned invalid JSON.",
      );
    }

    if (!response.ok) {
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

      if (response.status === 429) {
        return failure(
          429,
          "BACKEND_ERROR",
          "The AI verification engine is busy or temporarily limiting requests. Please wait a moment and try again.",
        );
      }

      if (response.status === 503) {
        return failure(
          503,
          "BACKEND_ERROR",
          "The backend could not complete the request.",
        );
      }

      return failure(
        502,
        "BACKEND_ERROR",
        "The backend could not complete the request.",
      );
    }

    return { ok: true, status: 200, data };
  } catch (error: unknown) {
    if (clientCancelled || options.signal?.aborted) {
      // 499 is a nonstandard, server-internal status indicating that the
      // caller has gone away. No successful response is promised to it.
      return failure(499, "BACKEND_UNAVAILABLE", "The request was cancelled.");
    }

    if (
      timedOut ||
      (error instanceof Error && error.name === "TimeoutError")
    ) {
      return failure(504, "BACKEND_TIMEOUT", "The backend request timed out.");
    }

    return failure(
      503,
      "BACKEND_UNAVAILABLE",
      "The backend service is unavailable.",
    );
  } finally {
    clearTimeout(timeoutId);
    options.signal?.removeEventListener("abort", onClientAbort);
  }
}
