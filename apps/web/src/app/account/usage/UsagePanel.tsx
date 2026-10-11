"use client";

import { useEffect, useState } from "react";

type Day = {
  date: string;
  total: number;
  successful: number;
  failed: number;
  rate_limited: number;
};

type Statistics = {
  window_days: number;
  total_requests: number;
  successful_requests: number;
  failed_requests: number;
  rate_limited_requests: number;
  average_latency_ms: number;
  daily: Day[];
};

export default function UsagePanel() {
  const [days, setDays] = useState<7 | 30 | 90>(30);
  const [stats, setStats] = useState<Statistics | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Discard results from obsolete requests without aborting shared fetches.
    // This avoids development-mode AbortError overlays during React remounts.
    let active = true;

    async function load() {
      try {
        const response = await fetch(`/api/account/usage?days=${days}`, {
          method: "GET",
          cache: "no-store",
        });
        if (!response.ok) throw new Error("Statistics are currently unavailable.");
        const result: Statistics = await response.json();
        if (active) setStats(result);
      } catch {
        if (active) {
          setError("Unable to load usage history right now. Please try again later.");
        }
      } finally {
        if (active) setLoading(false);
      }
    }

    void load();
    return () => {
      active = false;
    };
  }, [days]);

  const maxDaily = Math.max(1, ...(stats?.daily.map((day) => day.total) ?? []));

  return (
    <section className="space-y-5" aria-label="Verification usage statistics">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-semibold">Verification usage</h2>
        <label className="flex items-center gap-2 text-sm text-slate-300">
          Period
          <select
            className="rounded border border-slate-600 bg-slate-800 p-2 text-white"
            value={days}
            onChange={(event) => {
              setStats(null);
              setError("");
              setLoading(true);
              setDays(Number(event.target.value) as 7 | 30 | 90);
            }}
          >
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>
        </label>
      </div>

      {loading && <p role="status">Loading usage statistics…</p>}
      {error && <p role="alert" className="text-amber-300">{error}</p>}

      {stats && !loading && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {[
              ["Total requests", stats.total_requests],
              ["Successful", stats.successful_requests],
              ["Failed", stats.failed_requests],
              ["Rate-limited", stats.rate_limited_requests],
              ["Avg. response time", `${stats.average_latency_ms} ms`],
            ].map(([label, value]) => (
              <div key={label} className="rounded-lg border border-slate-700 bg-slate-900 p-4">
                <p className="text-xs text-slate-400">{label}</p>
                <p className="mt-1 text-xl font-semibold">{value}</p>
              </div>
            ))}
          </div>
          <div className="rounded-lg border border-slate-700 p-4">
            <h3 className="mb-3 font-medium">Daily requests (UTC)</h3>
            {stats.total_requests === 0 ? (
              <p className="text-sm text-slate-400">
                No recorded verification requests during this period.
              </p>
            ) : (
              <div className="max-h-72 space-y-2 overflow-y-auto">
                {stats.daily.map((day) => (
                  <div key={day.date} className="flex items-center gap-3 text-xs">
                    <time className="w-24 shrink-0 text-slate-400">{day.date}</time>
                    <div className="h-3 flex-1 rounded bg-slate-800">
                      <div
                        className="h-3 rounded bg-blue-500"
                        style={{ width: `${(day.total / maxDaily) * 100}%` }}
                      />
                    </div>
                    <span className="w-8 text-right">{day.total}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
          <p className="text-xs text-slate-400">
            Counts come from best-effort database history; they may be incomplete during
            database outages. These figures are not billing or live quota balances.
          </p>
        </>
      )}
    </section>
  );
}
