import { NextResponse } from "next/server";
import { auth } from "@/auth";



type DailyUsage = {
  date: string;
  total: number;
  successful: number;
  failed: number;
  rate_limited: number;
};

type UsageStatistics = {
  window_days: number;
  total_requests: number;
  successful_requests: number;
  failed_requests: number;
  rate_limited_requests: number;
  average_latency_ms: number;
  daily: DailyUsage[];
};

function errorResponse(status: number, message: string) {
  return NextResponse.json(
    { message },
    { status, headers: { "Cache-Control": "no-store" } },
  );
}

function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isUsageStatistics(value: unknown, days: number): value is UsageStatistics {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const data = value as Record<string, unknown>;
  if (
    data.window_days !== days ||
    !isCount(data.total_requests) ||
    !isCount(data.successful_requests) ||
    !isCount(data.failed_requests) ||
    !isCount(data.rate_limited_requests) ||
    typeof data.average_latency_ms !== "number" ||
    !Number.isFinite(data.average_latency_ms) ||
    data.average_latency_ms < 0 ||
    !Array.isArray(data.daily) ||
    data.daily.length !== days
  ) {
    return false;
  }
  return data.daily.every((row: unknown) => {
    if (typeof row !== "object" || row === null || Array.isArray(row)) return false;
    const item = row as Record<string, unknown>;
    return (
      typeof item.date === "string" && /^\d{4}-\d{2}-\d{2}$/.test(item.date) &&
      isCount(item.total) &&
      isCount(item.successful) &&
      isCount(item.failed) &&
      isCount(item.rate_limited)
    );
  });
}

export async function GET(request: Request) {
  // Auth.js session is the only source for the subject. Never take a user ID
  // from URL parameters, cookies outside Auth.js, or browser request headers.
  let verifiedUserId: string | undefined;
  try {
    const session = await auth();
    verifiedUserId = session?.user?.id;
  } catch {
    return errorResponse(503, "Authentication is temporarily unavailable.");
  }
  if (!verifiedUserId) return errorResponse(401, "Sign in to view your usage.");

  const query = new URL(request.url).searchParams;
  const values = query.getAll("days");
  const days = values.length === 0 ? "30" : values.length === 1 ? values[0] : "";
  if (!(["7", "30", "90"] as string[]).includes(days)) {
    return errorResponse(400, "days must be 7, 30, or 90.");
  }

  const baseUrl = process.env.API_BASE_URL?.trim();
  const token = process.env.INTERNAL_API_TOKEN?.trim();
  if (!baseUrl || !token || token.length < 32) {
    return errorResponse(503, "Usage statistics are not configured.");
  }

  let backendUrl: URL;
  try {
    const base = new URL(baseUrl);
    if (
      !["http:", "https:"].includes(base.protocol) ||
      (process.env.NODE_ENV === "production" && base.protocol !== "https:") ||
      base.username || base.password || base.search || base.hash
    ) {
      return errorResponse(503, "The backend URL is invalid.");
    }
    backendUrl = new URL(`/api/v1/account/usage?days=${days}`, base.origin);
  } catch {
    return errorResponse(503, "The backend URL is invalid.");
  }

  try {
    const upstream = await fetch(backendUrl, {
      method: "GET",
      headers: {
        "X-Service-Token": token,
        "X-Verified-User": verifiedUserId,
      },
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(8_000),
    });
    if (!upstream.ok) {
      return errorResponse(
        upstream.status === 503 ? 503 : 502,
        "Usage statistics are temporarily unavailable.",
      );
    }
    const data: unknown = await upstream.json();
    if (!isUsageStatistics(data, Number(days))) {
      return errorResponse(502, "The backend returned unexpected usage statistics.");
    }
    // Whitelist fields; never forward any unexpected backend properties.
    const sanitized: UsageStatistics = {
      window_days: data.window_days,
      total_requests: data.total_requests,
      successful_requests: data.successful_requests,
      failed_requests: data.failed_requests,
      rate_limited_requests: data.rate_limited_requests,
      average_latency_ms: data.average_latency_ms,
      daily: data.daily.map((day) => ({
        date: day.date,
        total: day.total,
        successful: day.successful,
        failed: day.failed,
        rate_limited: day.rate_limited,
      })),
    };
    return NextResponse.json(sanitized, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return errorResponse(503, "Usage statistics are temporarily unavailable.");
  }
}
