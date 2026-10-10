import { NextResponse } from "next/server";
import type {
  ApiErrorCode,
  VerificationRequest,
  VerificationResponse,
} from "@/lib/api/contracts";
import { requestBackend } from "@/lib/api/server";
import { auth } from "@/auth";

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

// Decode an actual byte-limited stream. Content-Length alone is not trustworthy.
async function parseLimitedJson(request: Request, maxBytes: number): Promise<
  | { ok: true; value: unknown }
  | { ok: false; status: number; message: string }
> {
  if (!request.body) {
    return { ok: false, status: 400, message: "JSON request body is required." };
  }
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let received = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      received += value.byteLength;
      if (received > maxBytes) {
        await reader.cancel();
        return { ok: false, status: 413, message: "Request body is too large." };
      }
      chunks.push(value);
    }
    const bytes = new Uint8Array(received);
    let offset = 0;
    for (const chunk of chunks) {
      bytes.set(chunk, offset);
      offset += chunk.byteLength;
    }
    return { ok: true, value: JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) };
  } catch {
    return { ok: false, status: 400, message: "Request body must be valid JSON." };
  } finally {
    reader.releaseLock();
  }
}

export async function POST(request: Request) {
  const isProduction = process.env.NODE_ENV === "production";
  const loginRequired = isProduction || process.env.VERIFY_REQUIRE_LOGIN === "true";
  let verifiedUserId: string | undefined;

  if (loginRequired) {
    // Production refuses requests until all OAuth and service secrets exist.
    if (
      isProduction &&
      (!process.env.AUTH_SECRET || !process.env.AUTH_GOOGLE_ID ||
        !process.env.AUTH_GOOGLE_SECRET || !process.env.INTERNAL_API_TOKEN)
    ) {
      return errorResponse(503, "BACKEND_NOT_CONFIGURED", "Secure verification is not configured.");
    }

    // Same-origin POSTs only; do not accept credentialed cross-origin requests.
    const origin = request.headers.get("origin");
    const fetchSite = request.headers.get("sec-fetch-site");
    if ((origin && origin !== new URL(request.url).origin) || fetchSite === "cross-site") {
      return errorResponse(403, "FORBIDDEN", "Cross-origin verification is not permitted.");
    }

    try {
      const session = await auth();
      if (session?.user?.id) verifiedUserId = session.user.id;
    } catch {
      return errorResponse(503, "BACKEND_UNAVAILABLE", "Authentication is temporarily unavailable.");
    }
    if (!verifiedUserId) {
      return errorResponse(401, "AUTH_REQUIRED", "Sign in at /account before verifying claims.");
    }
  }

  if (!request.headers.get("content-type")?.toLowerCase().startsWith("application/json")) {
    return errorResponse(415, "INVALID_REQUEST", "Content-Type must be application/json.");
  }

  const contentLength = Number(request.headers.get("content-length") ?? "0");
  if (!Number.isFinite(contentLength) || contentLength > 10_000 || contentLength < 0) {
    return errorResponse(413, "INVALID_REQUEST", "Request body is too large.");
  }

  const parsed = await parseLimitedJson(request, 10_000);
  if (!parsed.ok) {
    return errorResponse(parsed.status, "INVALID_REQUEST", parsed.message);
  }
  const incoming = parsed.value;

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
  const result = await requestBackend("/api/v1/verify", {
    method: "POST", body, verifiedUserId,
  });

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
