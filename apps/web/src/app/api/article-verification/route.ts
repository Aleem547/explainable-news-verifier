/** Server-only preview proxy. Never send service tokens or OAuth data to the browser. */
import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { requestBackend } from "@/lib/api/server";
import { isArticleVerificationReport } from "@/lib/api/article-contracts";
import type { ApiErrorCode } from "@/lib/api/contracts";

export const maxDuration = 120;

function fail(status: number, code: ApiErrorCode, message: string) {
  return NextResponse.json({ code, message }, { status, headers: { "Cache-Control": "no-store" } });
}

async function readBoundedJson(request: Request, maxBytes: number): Promise<unknown> {
  if (!request.body) throw new Error("missing_body");
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maxBytes) throw new Error("body_too_large");
      chunks.push(value);
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } finally {
    reader.releaseLock();
  }
}

export async function POST(request: Request) {
  if (process.env.ARTICLE_VERIFICATION_ENABLED !== "true") {
    return fail(503, "PRODUCTION_ROUTE_DISABLED", "Article verification preview is disabled.");
  }
  const isProduction = process.env.NODE_ENV === "production";
  if (isProduction && (!process.env.INTERNAL_API_TOKEN || process.env.INTERNAL_API_TOKEN.length < 32 ||
      !process.env.AUTH_SECRET || !process.env.AUTH_GOOGLE_ID || !process.env.AUTH_GOOGLE_SECRET)) {
    return fail(503, "BACKEND_NOT_CONFIGURED", "Secure article verification is not configured.");
  }
  if (request.signal.aborted) return fail(499, "BACKEND_UNAVAILABLE", "Request cancelled.");
  const origin = request.headers.get("origin");
  if ((origin && origin !== new URL(request.url).origin) ||
      request.headers.get("sec-fetch-site") === "cross-site") {
    return fail(403, "FORBIDDEN", "Cross-origin article verification is not permitted.");
  }
  let subject: string | undefined;
  try { subject = (await auth())?.user?.id; } catch {
    return fail(503, "BACKEND_UNAVAILABLE", "Authentication is temporarily unavailable.");
  }
  if (!subject) return fail(401, "AUTH_REQUIRED", "Sign in before verifying articles.");
  if (!/^application\/json(?:\s*;.*)?$/i.test(request.headers.get("content-type") ?? "")) {
    return fail(415, "INVALID_REQUEST", "Content-Type must be application/json.");
  }
  const length = Number(request.headers.get("content-length") ?? "0");
  if (!Number.isFinite(length) || length < 0 || length > 12_000) {
    return fail(413, "INVALID_REQUEST", "Request body is too large.");
  }
  let body: unknown;
  try { body = await readBoundedJson(request, 12_000); }
  catch { return fail(400, "INVALID_REQUEST", "Invalid or oversized article JSON."); }
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return fail(422, "INVALID_REQUEST", "An article object is required.");
  }
  const data = body as Record<string, unknown>;
  if (Object.keys(data).some((key) => !["kind", "text", "title"].includes(key)) ||
      data.kind !== "pasted" || typeof data.text !== "string" ||
      data.text.length < 100 || data.text.length > 8_000 ||
      new TextEncoder().encode(data.text).length > 10_000 ||
      (data.title !== undefined && (typeof data.title !== "string" || data.title.length > 300))) {
    return fail(422, "INVALID_REQUEST", "Submit a pasted plaintext article of 100–8,000 characters.");
  }
  const result = await requestBackend("/api/v1/article/verify", {
    method: "POST",
    body: { kind: "pasted", text: data.text, ...(data.title === undefined ? {} : { title: data.title }) },
    verifiedUserId: subject,
    signal: request.signal,
    timeoutMs: 115_000,
  });
  if (!result.ok) return NextResponse.json(result.error, {
    status: result.status, headers: { "Cache-Control": "no-store" },
  });
  if (!isArticleVerificationReport(result.data)) {
    return fail(502, "INVALID_BACKEND_RESPONSE", "The article report was invalid.");
  }
  return NextResponse.json(result.data, { headers: { "Cache-Control": "no-store" } });
}
