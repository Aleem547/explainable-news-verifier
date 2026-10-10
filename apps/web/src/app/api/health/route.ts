import { NextResponse } from "next/server";
import type { BackendHealthResponse } from "@/lib/api/contracts";
import { requestBackend } from "@/lib/api/server";


export async function GET() {
  const result = await requestBackend("/api/v1/ready", {
    method: "GET",
    timeoutMs: 5_000,
  });

  if (!result.ok) {
    return NextResponse.json(
      { status: "unavailable", checked: "backend_readiness", ...result.error },
      { status: result.status, headers: { "Cache-Control": "no-store" } },
    );
  }

  // FastAPI /ready is the authoritative dependency readiness endpoint.
  const response: BackendHealthResponse = {
    status: "ready",
    checked: "backend_readiness",
  };
  return NextResponse.json(response, {
    headers: { "Cache-Control": "no-store" },
  });
}
