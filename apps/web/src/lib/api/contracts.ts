/** Types generated from FastAPI's OpenAPI contract. Do not manually edit schema.d.ts. */
import type { paths } from "./schema";

type VerificationEndpoint = paths["/api/v1/verify"]["post"];

export type VerificationRequest =
  VerificationEndpoint["requestBody"]["content"]["application/json"];

export type VerificationResponse =
  VerificationEndpoint["responses"][200]["content"]["application/json"];

export type VerifiedEvidence = VerificationResponse["evidence"][number];

export type ApiErrorCode =
  | "INVALID_REQUEST"
  | "BACKEND_NOT_CONFIGURED"
  | "BACKEND_UNAVAILABLE"
  | "BACKEND_TIMEOUT"
  | "BACKEND_REJECTED_REQUEST"
  | "BACKEND_ERROR"
  | "INVALID_BACKEND_RESPONSE"
  | "PRODUCTION_ROUTE_DISABLED"
  | "AUTH_REQUIRED"
  | "FORBIDDEN";

export interface ApiErrorResponse {
  code: ApiErrorCode;
  message: string;
  details?: unknown;
}

export interface BackendHealthResponse {
  status: "ready" | "unavailable";
  checked: "backend_readiness";
}
