"use client";

import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { AlertCircle, ArrowRight, LoaderCircle, ShieldAlert } from "lucide-react";
import { EvidenceCard } from "./evidence-card";
import { ApiClientError, verifyClaim } from "@/lib/api/client";
import type { VerificationResponse } from "@/lib/api/contracts";

type EvidenceFilter = "all" | "accepted" | "not-accepted";

const EXAMPLES = [
  "The Indian Army is a military force.",
  "The Eiffel Tower is located in Paris.",
] as const;

const VERDICT_PRESENTATION: Record<
  VerificationResponse["verdict"],
  { label: string; className: string; explanation: string }
> = {
  SUPPORTING_EVIDENCE: {
    label: "Supporting evidence",
    className: "border-emerald-400/25 bg-emerald-400/10 text-emerald-300",
    explanation: "The accepted evidence supports this claim within the assessed corpus.",
  },
  REFUTING_EVIDENCE: {
    label: "Refuting evidence",
    className: "border-rose-400/25 bg-rose-400/10 text-rose-300",
    explanation: "The accepted evidence contradicts this claim within the assessed corpus.",
  },
  CONFLICTING_EVIDENCE: {
    label: "Conflicting evidence",
    className: "border-amber-400/25 bg-amber-400/10 text-amber-300",
    explanation: "The assessed corpus contains accepted evidence on opposing sides.",
  },
  INSUFFICIENT_EVIDENCE: {
    label: "Insufficient evidence",
    className: "border-slate-400/25 bg-slate-400/10 text-slate-200",
    explanation: "The system did not find enough admissible, decisive evidence to decide.",
  },
};

export function VerificationWorkspace() {
  const [claim, setClaim] = useState("");
  const [topK, setTopK] = useState(5);
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState<VerificationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<EvidenceFilter>("all");
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => controllerRef.current?.abort();
  }, []);

  function editClaim(next: string) {
    setClaim(next);
    setResult(null);
    setError(null);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalized = claim.trim();
    if (isLoading) return;

    if (normalized.length < 3 || normalized.length > 2000) {
      setError("Enter a claim containing 3 to 2,000 characters.");
      return;
    }

    const controller = new AbortController();
    controllerRef.current = controller;
    setError(null);
    setResult(null);
    setFilter("all");
    setIsLoading(true);

    // The Next.js route has a 120-second backend request timeout.
    const timer = window.setTimeout(() => controller.abort(), 135_000);

    try {
      const response = await verifyClaim({ claim: normalized, top_k: topK }, controller.signal);
      if (controllerRef.current !== controller) return;
      setResult(response);
    } catch (cause: unknown) {
      if (controllerRef.current !== controller) return;
      if (controller.signal.aborted) {
        setError("Verification was cancelled or exceeded the browser time limit.");
      } else if (cause instanceof ApiClientError) {
        setError(cause.message);
      } else {
        setError("An unexpected error occurred. Please try again.");
      }
    } finally {
      window.clearTimeout(timer);
      if (controllerRef.current === controller) {
        controllerRef.current = null;
        setIsLoading(false);
      }
    }
  }

  function cancel() {
    controllerRef.current?.abort();
    controllerRef.current = null;
    setIsLoading(false);
    setError("Verification cancelled.");
  }

  const visibleEvidence = result?.evidence.filter((item) => {
    if (filter === "accepted") return item.accepted;
    if (filter === "not-accepted") return !item.accepted;
    return true;
  }) ?? [];

  const verdict = result ? VERDICT_PRESENTATION[result.verdict] : null;

  return (
    <div className="space-y-7">
      <section className="rounded-2xl border border-white/10 bg-[#111a29] p-6 md:p-8">
        <h2 className="text-xl font-semibold text-white">Analyze a factual claim</h2>
        <p className="mt-2 text-sm leading-6 text-slate-400">
          Enter a specific statement. The system searches evidence, evaluates
          sentence-level relations, and returns an auditable result.
        </p>

        <form onSubmit={submit} className="mt-6 space-y-5">
          <div>
            <label htmlFor="claim-text" className="mb-2 block text-sm font-medium text-slate-200">
              Claim to verify
            </label>
            <textarea
              id="claim-text"
              name="claim"
              value={claim}
              onChange={(event) => editClaim(event.target.value)}
              disabled={isLoading}
              minLength={3}
              maxLength={2000}
              required
              rows={4}
              placeholder="Enter a claim, e.g. The Indian Army is a military force."
              className="w-full resize-y rounded-xl border border-white/15 bg-[#0a0f19] p-4 text-sm leading-6 text-white outline-none placeholder:text-slate-500 focus:border-blue-400 disabled:opacity-60"
              aria-describedby="claim-help"
            />
            <p id="claim-help" className="mt-2 text-xs text-slate-500">
              {claim.length} / 2,000 characters · Minimum 3 characters
            </p>
          </div>

          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <label htmlFor="top-k" className="mb-2 block text-sm font-medium text-slate-200">
                Evidence limit
              </label>
              <select
                id="top-k"
                value={topK}
                onChange={(event) => {
                  setTopK(Number(event.target.value));
                  setResult(null);
                }}
                disabled={isLoading}
                className="rounded-xl border border-white/15 bg-[#0a0f19] px-4 py-3 text-sm text-slate-100 focus:border-blue-400"
              >
                <option value={3}>3 passages</option>
                <option value={5}>5 passages</option>
                <option value={10}>10 passages</option>
                <option value={20}>20 passages</option>
              </select>
            </div>
            <div className="flex gap-3">
              {isLoading && (
                <button
                  type="button"
                  onClick={cancel}
                  className="rounded-xl border border-white/20 px-5 py-3 text-sm font-medium text-slate-200 hover:bg-white/10"
                >
                  Cancel
                </button>
              )}
              <button
                type="submit"
                disabled={isLoading || claim.trim().length < 3}
                className="inline-flex items-center justify-center gap-2 rounded-xl bg-blue-500 px-5 py-3 text-sm font-semibold text-white hover:bg-blue-400 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isLoading ? (
                  <><LoaderCircle size={18} className="animate-spin" aria-hidden="true" /> Verifying…</>
                ) : (
                  <>Verify claim <ArrowRight size={18} aria-hidden="true" /></>
                )}
              </button>
            </div>
          </div>
        </form>

        <div className="mt-6 flex flex-wrap items-center gap-2">
          <span className="text-xs text-slate-500">Try an example:</span>
          {EXAMPLES.map((example) => (
            <button
              type="button"
              key={example}
              disabled={isLoading}
              onClick={() => editClaim(example)}
              className="rounded-full border border-white/10 px-3 py-1.5 text-left text-xs text-slate-300 hover:border-blue-400/50 hover:text-white disabled:opacity-50"
            >
              {example}
            </button>
          ))}
        </div>
      </section>

      {isLoading && (
        <div role="status" aria-live="polite" className="flex items-center gap-3 rounded-xl border border-blue-400/20 bg-blue-400/5 p-5 text-sm text-blue-200">
          <LoaderCircle size={19} className="animate-spin" aria-hidden="true" />
          Retrieving and assessing evidence. The initial model request may take longer.
        </div>
      )}

      {error && (
        <div role="alert" className="flex items-start gap-3 rounded-xl border border-rose-400/25 bg-rose-400/10 p-5 text-sm text-rose-200">
          <AlertCircle size={19} className="mt-0.5 shrink-0" aria-hidden="true" />
          <p>{error}</p>
        </div>
      )}

      {result && verdict && (
        <section aria-labelledby="verification-result-title" className="space-y-6">
          <div className="rounded-2xl border border-white/10 bg-[#111a29] p-6 md:p-8">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <h2 id="verification-result-title" className="text-xl font-semibold text-white">
                Verification result
              </h2>
              <span className={`rounded-full border px-4 py-2 text-sm font-semibold ${verdict.className}`}>
                {verdict.label}
              </span>
            </div>
            <p className="mt-5 break-words text-base font-medium text-slate-100">
              {result.claim}
            </p>
            <p className="mt-3 text-sm leading-6 text-slate-300">{verdict.explanation}</p>

            <dl className="mt-6 grid grid-cols-2 gap-4 border-t border-white/10 pt-6 sm:grid-cols-3 lg:grid-cols-5">
              <div><dt className="text-xs text-slate-500">Retrieved</dt><dd className="mt-1 text-xl font-semibold">{result.retrieved_count}</dd></div>
              <div><dt className="text-xs text-slate-500">Assessed</dt><dd className="mt-1 text-xl font-semibold">{result.assessed_count}</dd></div>
              <div><dt className="text-xs text-slate-500">Supporting pages</dt><dd className="mt-1 text-xl font-semibold">{result.supporting_pages.length}</dd></div>
              <div><dt className="text-xs text-slate-500">Refuting pages</dt><dd className="mt-1 text-xl font-semibold">{result.refuting_pages.length}</dd></div>
              <div><dt className="text-xs text-slate-500">Inference time</dt><dd className="mt-1 text-xl font-semibold">{(result.latency_ms / 1000).toFixed(1)}s</dd></div>
            </dl>

            <div className="mt-6 flex items-start gap-3 rounded-xl border border-amber-400/20 bg-amber-400/5 p-4 text-sm leading-6 text-amber-100">
              <ShieldAlert size={20} className="mt-0.5 shrink-0" aria-hidden="true" />
              <div>
                <p className="font-semibold">Evidence limitation</p>
                <p className="mt-1">{result.warning}</p>
                <p className="mt-2 text-xs text-amber-200/80">
                  Corroboration: {result.corroboration_status ?? "Not established"}
                </p>
              </div>
            </div>
            <p className="mt-4 text-xs text-slate-500">
              Evidence aggregation reason: {(result.aggregation_reason ?? "NO_DECISIVE_EVIDENCE").replaceAll("_", " ")}
              {typeof result.admissibility_blocked_count === "number" && (
                <> · Admissibility-blocked: {result.admissibility_blocked_count}</>
              )}
            </p>
          </div>

          <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="text-xl font-semibold text-white">Assessed evidence</h3>
                <p className="mt-1 text-sm text-slate-400">
                  Showing {visibleEvidence.length} of {result.evidence.length} passages
                </p>
              </div>
              <label className="flex items-center gap-2 text-sm text-slate-300">
                Filter
                <select
                  value={filter}
                  onChange={(event) => setFilter(event.target.value as EvidenceFilter)}
                  className="rounded-lg border border-white/15 bg-[#111a29] px-3 py-2 text-sm text-slate-100"
                >
                  <option value="all">All evidence</option>
                  <option value="accepted">Accepted only</option>
                  <option value="not-accepted">Not accepted</option>
                </select>
              </label>
            </div>
            {visibleEvidence.length ? (
              visibleEvidence.map((item) => (
                <EvidenceCard
                  key={`${item.rank}:${item.page_id}:${item.sentence_id}`}
                  evidence={item}
                  confidenceThreshold={result.confidence_threshold}
                />
              ))
            ) : (
              <p className="rounded-xl border border-white/10 bg-[#111a29] p-5 text-sm text-slate-400">
                No evidence matches this filter. This does not mean the claim is false.
              </p>
            )}
          </div>
        </section>
      )}
    </div>
  );
}
