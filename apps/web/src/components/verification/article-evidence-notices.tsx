import type { ArticleClaimResult } from "@/lib/api/article-contracts";

function evidenceNote(claim: ArticleClaimResult): string {
  if (claim.execution_status === "FAILED") {
    return "This claim could not be assessed. Try again before using this result.";
  }
  if (claim.execution_status === "UNAVAILABLE") {
    return "Evidence assessment was unavailable for this claim.";
  }
  if (claim.execution_status === "SKIPPED_LIMIT") {
    return "This claim was skipped because the preview assesses one claim per request.";
  }

  const reviewed = claim.external_reviewed_corroboration;
  if (reviewed?.corroboration_established === true) {
    if (reviewed.status === "REVIEWED_SUPPORT") {
      return "Reviewed cross-source support applies only to this claim and the captured evidence.";
    }
    if (reviewed.status === "REVIEWED_REFUTATION") {
      return "Reviewed cross-source refutation applies only to this claim and the captured evidence.";
    }
  }
  if (reviewed?.status === "CONFLICTING_EVIDENCE") {
    return "The admitted evidence contains both support and refutation. Cross-source corroboration remains unresolved.";
  }
  if (claim.external_verdict === "INSUFFICIENT_STORED_EVIDENCE") {
    return "The stored external evidence is insufficient for this claim. This does not establish that the claim is false.";
  }
  return "Reviewed cross-source corroboration is not established for this claim. Relevant evidence and a valid reporting-origin review are required.";
}

/** Present the guarded report without changing any evidence or review decision. */
export function ArticleEvidenceNotices({ claim }: { claim: ArticleClaimResult }) {
  return <section aria-label="Evidence notes" className="mt-4 rounded-lg border border-white/10 p-3 text-xs leading-5 text-slate-300">
    <p className="font-medium">Evidence notes</p>
    <p className="mt-1">{evidenceNote(claim)}</p>
    <p className="mt-1 text-slate-400">NLI scores describe textual relations, not factual truth probabilities. No article-wide truth rating is provided.</p>
    {claim.warning_codes.length > 0 && <details className="mt-3 text-slate-400">
      <summary className="cursor-pointer">Technical diagnostics ({claim.warning_codes.length})</summary>
      <p className="mt-2">Raw codes from the evidence and origin-audit stages are retained below. The claim-specific reviewed decision is shown separately above.</p>
      <ul className="mt-2 space-y-1 font-mono">
        {claim.warning_codes.map(code => <li key={code} className="break-words [overflow-wrap:anywhere]">{code}</li>)}
      </ul>
    </details>}
  </section>;
}
