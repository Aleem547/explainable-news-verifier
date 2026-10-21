"use client";

import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { AlertCircle, LoaderCircle, ShieldAlert } from "lucide-react";
import type { ArticleVerificationReport } from "@/lib/api/article-contracts";
import { isArticleVerificationReport } from "@/lib/api/article-contracts";

const isHttps = (url: string) => {
  try { const parsed = new URL(url); return parsed.protocol === "https:" && !parsed.username && !parsed.password; }
  catch { return false; }
};

export function ArticleVerificationWorkspace({ enabled }: { enabled: boolean }) {
  const [mode, setMode] = useState<"pasted" | "url">("pasted");
  const [text, setText] = useState("");
  const [title, setTitle] = useState("");
  const [report, setReport] = useState<ArticleVerificationReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestRef = useRef<AbortController | null>(null);

  useEffect(() => () => requestRef.current?.abort(), []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!enabled || busy || mode !== "pasted") return;
    if (text.length < 100 || text.length > 8000 || new TextEncoder().encode(text).length > 10_000) {
      setError("Paste 100 to 8,000 characters (no more than 10 KB of UTF-8 text).");
      return;
    }
    const controller = new AbortController();
    requestRef.current = controller;
    setReport(null); setError(null); setBusy(true);
    const timer = window.setTimeout(() => controller.abort(), 119_000);
    try {
      const response = await fetch("/api/article-verification", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: "pasted", text, ...(title.trim() ? { title: title.trim() } : {}) }),
        signal: controller.signal, cache: "no-store",
      });
      const raw: unknown = await response.json();
      if (requestRef.current !== controller) return;
      if (!response.ok) {
        const message = typeof raw === "object" && raw !== null && "message" in raw &&
          typeof raw.message === "string" ? raw.message : "Unable to verify this article.";
        throw new Error(message);
      }
      if (!isArticleVerificationReport(raw)) throw new Error("Invalid article verification response.");
      setReport(raw);
    } catch (cause) {
      if (requestRef.current === controller) {
        setError(controller.signal.aborted ? "Request cancelled or timed out; the model may still be finishing server-side." :
          cause instanceof Error ? cause.message : "Article verification was unavailable.");
      }
    } finally {
      window.clearTimeout(timer);
      if (requestRef.current === controller) { requestRef.current = null; setBusy(false); }
    }
  }

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-amber-400/25 bg-amber-400/10 p-4 text-sm leading-6 text-amber-100">
        <ShieldAlert className="mb-2 size-5" aria-hidden="true" />
        Preview: only pasted plaintext is supported. Inputs are not independent evidence. One factual claim is assessed per request; remaining candidates are marked skipped. No article-wide true/false rating is produced.
      </div>
      <div className="flex gap-2" role="group" aria-label="Article input type">
        <button type="button" onClick={() => { setMode("pasted"); setReport(null); setError(null); }}
          aria-pressed={mode === "pasted"}
          className={`rounded-lg border px-4 py-2 text-sm ${mode === "pasted" ? "border-blue-400 bg-blue-500/20 text-white" : "border-white/10 text-slate-400"}`}>
          Paste article
        </button>
        <button type="button" onClick={() => { setMode("url"); setReport(null); setError(null); }}
          aria-pressed={mode === "url"}
          className={`rounded-lg border px-4 py-2 text-sm ${mode === "url" ? "border-blue-400 bg-blue-500/20 text-white" : "border-white/10 text-slate-400"}`}>
          Article URL
        </button>
      </div>
      {mode === "url" ? (
        <div className="rounded-xl border border-white/10 bg-[#101827] p-6 text-slate-300">
          URL verification is not enabled in this preview. It requires a server-validated discovery record and publisher access permission. Paste public article text that you have permission to use instead; the content will remain labeled user-supplied.
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-4 rounded-xl border border-white/10 bg-[#101827] p-6">
          <label className="block text-sm font-medium text-slate-200" htmlFor="article-title">Optional article title</label>
          <input id="article-title" type="text" maxLength={300} value={title} disabled={!enabled || busy}
            onChange={(event) => { setTitle(event.target.value); setReport(null); }}
            className="w-full rounded-md border border-white/20 bg-[#080e18] px-3 py-2 text-white" />
          <label className="block text-sm font-medium text-slate-200" htmlFor="article-text">Article text</label>
          <textarea id="article-text" rows={11} maxLength={8000} value={text} disabled={!enabled || busy}
            onChange={(event) => { setText(event.target.value); setReport(null); }}
            className="w-full rounded-md border border-white/20 bg-[#080e18] px-3 py-2 leading-relaxed text-white"
            placeholder="Paste the full article text here. Avoid including private or sensitive information." />
          <p className="text-xs text-slate-400">{text.length.toLocaleString()} / 8,000 characters · Sign in required · Source not treated as independently published evidence</p>
          {error && <p role="alert" className="flex items-start gap-2 text-sm text-rose-300"><AlertCircle className="mt-1 size-4 shrink-0" />{error}</p>}
          <div className="flex gap-3">
            <button type="submit" disabled={!enabled || busy}
              className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-5 py-2 font-medium text-white disabled:opacity-50">
              {busy && <LoaderCircle className="size-4 animate-spin" />} {busy ? "Verifying…" : "Verify article preview"}
            </button>
            {busy && <button type="button" className="rounded-md border border-white/20 px-4 py-2 text-sm" onClick={() => requestRef.current?.abort()}>Cancel</button>}
          </div>
          {!enabled && <p className="text-sm text-amber-300">This preview is disabled by the deployment operator.</p>}
        </form>
      )}
      {report && <section aria-label="Article evidence report" className="space-y-5">
        <header className="rounded-xl border border-white/10 p-5">
          <h2 className="text-xl font-semibold">Article analysis</h2>
          <p className="mt-2 text-sm text-slate-400">{report.candidate_count} candidates · {report.assessed_count} assessed · {report.unavailable_count} unavailable · {report.failed_count} failed · {report.skipped_count} skipped</p>
          <p className="mt-2 text-xs text-amber-300">Editorial independence not established. Article-wide truth verdict unavailable.</p>
        </header>
        {report.claims.map((claim) => (
          <article key={claim.candidate_id} className="rounded-xl border border-white/10 bg-[#101827] p-5">
            <p className="text-xs uppercase tracking-wide text-blue-300">{claim.execution_status} · paragraph {claim.paragraph_index + 1}</p>
            <h3 className="mt-2 font-medium text-white">{claim.literal_text}</h3>
            <p className="mt-3 text-sm text-slate-300">Wikipedia: {claim.wikipedia_verdict ?? claim.wikipedia_status ?? "Not assessed"}</p>
            <p className="mt-1 text-sm text-slate-300">External evidence: {claim.external_verdict ?? claim.external_status ?? "Not assessed"}</p>
            {claim.cross_corpus_relationship && <p className="mt-1 text-xs text-slate-400">Cross-corpus relationship: {claim.cross_corpus_relationship.replaceAll("_", " ")}</p>}
            {claim.external_references.length > 0 && <div className="mt-4 space-y-2">
              <p className="text-xs font-medium text-slate-400">External source references (not independently verified)</p>
              {claim.external_references.map((ref) => (
                <p key={ref.citation_id} className="text-sm text-slate-300">
                  {isHttps(ref.article_url) ? <a href={ref.article_url} target="_blank" rel="noopener noreferrer" className="underline decoration-blue-500">{ref.publisher_domain}</a> : ref.publisher_domain}
                  {" · "}{ref.nli_label.toLowerCase()} (NLI score {ref.nli_confidence.toFixed(2)})
                </p>
              ))}
            </div>}
            {claim.warning_codes.length > 0 && <p className="mt-3 text-xs text-amber-300">{claim.warning_codes.join(" · ").replaceAll("_", " ")}</p>}
          </article>
        ))}
      </section>}
    </div>
  );
}
