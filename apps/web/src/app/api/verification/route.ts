import { NextResponse } from "next/server";
import type {
  ApiErrorCode,
  VerificationRequest,
  VerificationResponse,
} from "@/lib/api/contracts";
import { requestBackend } from "@/lib/api/server";

export const maxDuration = 120;

function errorResponse(status: number, code: ApiErrorCode, message: string) {
  return NextResponse.json(
    { code, message },
    { status, headers: { "Cache-Control": "no-store" } },
  );
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isValidVerificationResponse(value: unknown): value is VerificationResponse {
  if (!isObject(value)) return false;
  return (
    typeof value.claim === "string" &&
    [
      "SUPPORTING_EVIDENCE",
      "REFUTING_EVIDENCE",
      "CONFLICTING_EVIDENCE",
      "INSUFFICIENT_EVIDENCE",
    ].includes(String(value.verdict)) &&
    typeof value.warning === "string" &&
    typeof value.latency_ms === "number" &&
    typeof value.confidence_threshold === "number" &&
    typeof value.retrieved_count === "number" &&
    typeof value.assessed_count === "number" &&
    Array.isArray(value.supporting_pages) &&
    Array.isArray(value.refuting_pages) &&
    Array.isArray(value.evidence) &&
    value.evidence.every(
      (item: unknown) =>
        isObject(item) &&
        typeof item.text === "string" &&
        typeof item.page_id === "string" &&
        typeof item.nli_label === "string" &&
        typeof item.accepted === "boolean",
    )
  );
}

export async function POST(request: Request) {
  // A public, expensive inference endpoint needs authentication and shared rate
  // limiting before deployment. This stage intentionally permits development only.
  if (process.env.NODE_ENV === "production") {
    return errorResponse(
      503,
      "PRODUCTION_ROUTE_DISABLED",
      "Public verification is disabled until production access controls are configured.",
    );
  }

  if (!request.headers.get("content-type")?.toLowerCase().startsWith("application/json")) {
    return errorResponse(415, "INVALID_REQUEST", "Content-Type must be application/json.");
  }

  const contentLength = Number(request.headers.get("content-length") ?? "0");
  if (contentLength > 10_000) {
    return errorResponse(413, "INVALID_REQUEST", "Request body is too large.");
  }

  let incoming: unknown;
  try {
    incoming = await request.json();
  } catch {
    return errorResponse(400, "INVALID_REQUEST", "Request body must be valid JSON.");
  }

  if (!isObject(incoming) || typeof incoming.claim !== "string") {
    return errorResponse(422, "INVALID_REQUEST", "A claim string is required.");
  }

  const claim = incoming.claim.trim();
  if (claim.length < 3 || claim.length > 2000) {
    return errorResponse(422, "INVALID_REQUEST", "Claim must contain 3–2000 characters.");
  }

  const topK = incoming.top_k === undefined ? 5 : incoming.top_k;
  if (typeof topK !== "number" || !Number.isInteger(topK) || topK < 1 || topK > 20) {
    return errorResponse(422, "INVALID_REQUEST", "top_k must be an integer from 1 to 20.");
  }

  const body: VerificationRequest = { claim, top_k: topK };
  const result = await requestBackend("/api/v1/verify", { method: "POST", body });

  if (!result.ok) {
    return NextResponse.json(result.error, {
      status: result.status,
      headers: { "Cache-Control": "no-store" },
    });
  }

  if (!isValidVerificationResponse(result.data)) {
    return errorResponse(
      502,
      "INVALID_BACKEND_RESPONSE",
      "The backend returned an unexpected verification response.",
    );
  }

  return NextResponse.json(result.data, {
    headers: { "Cache-Control": "no-store" },
  });
}
