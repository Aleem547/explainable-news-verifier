/** Browser-safe API client. Calls Next.js routes, never the private FastAPI URL. */
import type {
  ApiErrorCode,
  ApiErrorResponse,
  BackendHealthResponse,
  VerificationRequest,
  VerificationResponse,
} from "./contracts";

export class ApiClientError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code: ApiErrorCode | "NETWORK_ERROR" | "INVALID_RESPONSE",
    public readonly details?: unknown,
  ) {
    super(message);
    this.name = "ApiClientError";
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

async function parseResponse<T>(response: Response): Promise<T> {
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new ApiClientError("The server returned invalid JSON.", response.status, "INVALID_RESPONSE");
  }

  if (!response.ok) {
    const data = payload as Partial<ApiErrorResponse>;
    throw new ApiClientError(
      isObject(data) && typeof data.message === "string"
        ? data.message
        : "The request could not be completed.",
      response.status,
      isObject(data) && typeof data.code === "string"
        ? (data.code as ApiErrorCode)
        : "INVALID_RESPONSE",
      isObject(data) ? data.details : undefined,
    );
  }

  return payload as T;
}

export async function getBackendHealth(signal?: AbortSignal): Promise<BackendHealthResponse> {
  let response: Response;
  try {
    response = await fetch("/api/health", { cache: "no-store", signal });
  } catch {
    throw new ApiClientError("Cannot reach the web application.", 0, "NETWORK_ERROR");
  }
  return parseResponse<BackendHealthResponse>(response);
}

export async function verifyClaim(
  request: VerificationRequest,
  signal?: AbortSignal,
): Promise<VerificationResponse> {
  let response: Response;
  try {
    response = await fetch("/api/verification", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      cache: "no-store",
      signal,
    });
  } catch {
    throw new ApiClientError("Cannot reach the web application.", 0, "NETWORK_ERROR");
  }
  return parseResponse<VerificationResponse>(response);
}
