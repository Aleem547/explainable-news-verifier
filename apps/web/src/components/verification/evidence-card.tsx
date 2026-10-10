import type { VerifiedEvidence } from "@/lib/api/contracts";

type EvidenceCardProps = {
  evidence: VerifiedEvidence;
  confidenceThreshold: number;
};

type EvidenceDecisionReason =
  | "ACCEPTED_DECISIVE"
  | "NEUTRAL_RELATION"
  | "BELOW_CONFIDENCE_THRESHOLD"
  | "SUBJECT_NOT_GROUNDED";

function decisionReason(
  evidence: VerifiedEvidence,
  threshold: number,
): EvidenceDecisionReason | null {
  // Existing OpenAPI-generated client types may predate this additive API field.
  // Keep a deterministic fallback while schema types are regenerated.
  const newer = evidence as VerifiedEvidence & { decision_reason?: string | null };
  const known: EvidenceDecisionReason[] = [
    "ACCEPTED_DECISIVE", "NEUTRAL_RELATION",
    "BELOW_CONFIDENCE_THRESHOLD", "SUBJECT_NOT_GROUNDED",
  ];
  if (newer.decision_reason && known.some((reason) => reason === newer.decision_reason)) {
    return newer.decision_reason as EvidenceDecisionReason;
  }
  if (evidence.nli_label === "NEUTRAL") return "NEUTRAL_RELATION";
  if (evidence.nli_confidence < threshold) return "BELOW_CONFIDENCE_THRESHOLD";
  if (evidence.admissibility_reason === "SUBJECT_NOT_GROUNDED") {
    return "SUBJECT_NOT_GROUNDED";
  }
  if (evidence.accepted) return "ACCEPTED_DECISIVE";
  return null;
}

function rejectionExplanation(reason: EvidenceDecisionReason | null, threshold: number): string | null {
  switch (reason) {
    case "NEUTRAL_RELATION":
      return "The NLI model judged this passage neutral. Neutral evidence cannot support or refute a claim, even at high confidence.";
    case "BELOW_CONFIDENCE_THRESHOLD":
      return `The NLI score is below the current decisive-evidence threshold (${threshold.toFixed(2)}). The sentence remains visible but cannot determine the verdict.`;
    case "SUBJECT_NOT_GROUNDED":
      return "The claim's named subject was not grounded in this passage or page title. A related name alone is insufficient.";
    case "ACCEPTED_DECISIVE":
      return null;
    default:
      return "This passage did not pass the decisive-evidence checks.";
  }
}

function displayReadableWikiText(value: string) {
  // Only replace explicit FEVER Wikipedia bracket placeholders for readability.
  // The untouched original is available in the expandable raw-evidence section.
  return value.replaceAll("-LRB-", "(").replaceAll("-RRB-", ")")
    .replaceAll("-LSB-", "[").replaceAll("-RSB-", "]")
    .replaceAll("-LCB-", "{").replaceAll("-RCB-", "}");
}

function displayLabel(value: string) {
  return value.replaceAll("_", " ");
}

function formatScore(value: number) {
  return Number.isFinite(value) ? value.toFixed(3) : "Not available";
}

export function EvidenceCard({ evidence, confidenceThreshold }: EvidenceCardProps) {
  const reason = decisionReason(evidence, confidenceThreshold);
  const explanation = evidence.accepted
    ? null
    : rejectionExplanation(reason, confidenceThreshold);
  const readableText = displayReadableWikiText(evidence.text);

  const nliColor =
    evidence.nli_label === "ENTAILMENT"
      ? "text-emerald-300"
      : evidence.nli_label === "CONTRADICTION"
        ? "text-rose-300"
        : "text-amber-300";

  return (
    <article className="rounded-2xl border border-white/10 bg-[#111a29] p-5 md:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-widest text-slate-500">
            Evidence #{evidence.rank}
          </p>
          <p className="mt-2 break-all text-sm font-semibold text-white">
            {evidence.page_id.replaceAll("_", " ")}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Corpus page ID: {evidence.page_id} · Sentence {evidence.sentence_id}
          </p>
        </div>
        <span
          className={`rounded-full border px-3 py-1.5 text-xs font-medium ${
            evidence.accepted
              ? "border-emerald-400/20 bg-emerald-400/10 text-emerald-300"
              : "border-slate-400/20 bg-slate-400/10 text-slate-300"
          }`}
        >
          {evidence.accepted ? "Accepted for aggregation" : "Not accepted"}
        </span>
      </div>

      <p className="mt-5 whitespace-pre-wrap break-words rounded-xl border border-white/5 bg-black/20 p-4 text-sm leading-7 text-slate-200">
        {readableText}
      </p>
      {readableText !== evidence.text && (
        <details className="mt-2 text-xs text-slate-400">
          <summary className="cursor-pointer hover:text-slate-200">Show original corpus text</summary>
          <pre className="mt-2 whitespace-pre-wrap break-words rounded-lg border border-white/10 p-3 font-sans leading-5">{evidence.text}</pre>
        </details>
      )}

      <dl className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <dt className="text-xs text-slate-500">NLI relation</dt>
          <dd className={`mt-1 text-sm font-medium ${nliColor}`}>
            {displayLabel(evidence.nli_label)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">NLI model score</dt>
          <dd className="mt-1 text-sm font-medium text-slate-100">
            {formatScore(evidence.nli_confidence)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Reranker score</dt>
          <dd className="mt-1 text-sm font-medium text-slate-100">
            {formatScore(evidence.cross_encoder_score)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Contribution</dt>
          <dd className="mt-1 break-words text-sm font-medium text-slate-100">
            {displayLabel(evidence.contribution_role ?? "NOT_DECISIVE")}
          </dd>
        </div>
      </dl>

      {explanation && (
        <div className="mt-4 rounded-lg border border-amber-400/20 bg-amber-400/5 p-3 text-sm text-amber-100">
          <p className="font-semibold">Not accepted: {displayLabel(reason ?? "OTHER_DECISION")}</p>
          <p className="mt-1 leading-6">{explanation}</p>
        </div>
      )}
      <p className="mt-4 text-xs leading-5 text-slate-500">
        The NLI score describes the sentence-level model output. It is not a
        calibrated probability that the claim is true.
      </p>
    </article>
  );
}
