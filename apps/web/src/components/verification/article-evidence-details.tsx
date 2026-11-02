import type { ArticleClaimResult, ArticleEvidenceReference } from "@/lib/api/article-contracts";
import { isArticleEvidenceUrl } from "@/lib/api/article-contracts";

function admissionLabel(ref: ArticleEvidenceReference): string {
  if (ref.decisive_evidence_admitted === true) {
    return ref.nli_label === "ENTAILMENT" ? "Used for provisional support" : "Used for provisional refutation";
  }
  return ref.decisive_evidence_admitted === false
    ? "Not used as decisive evidence" : "Admission review unavailable";
}

/** Receives only reports accepted by the shared public response guard. */
export function ArticleEvidenceDetails({ claim }: { claim: ArticleClaimResult }) {
  const audit = claim.external_origin_audit;
  const trusted = claim.external_trusted_origin_review;
  const corroboration = claim.external_reviewed_corroboration;
  const corroborationLabels = {
    REVIEWED_SUPPORT: "Reviewed cross-source support",
    REVIEWED_REFUTATION: "Reviewed cross-source refutation",
    CONFLICTING_EVIDENCE: "Conflicting evidence blocks corroboration",
    NOT_ESTABLISHED: "Cross-source corroboration not established",
  };
  const reviewLabels = {
    PENDING: "Awaiting authorized origin review",
    INCONCLUSIVE: "Reviewed: origin evidence remains inconclusive",
    DEPENDENCY_DOCUMENTED: "Reviewed: reporting dependency documented",
    REVIEWED_DISTINCT_REPORTING: "Operator reviewed distinct reporting",
    REVIEW_UNAVAILABLE: "Origin review could not be verified",
    NO_ELIGIBLE_PAIR: "No eligible reporting pair",
  };
  return <div className="mt-4 space-y-3">
    {corroboration && <section aria-label="Reviewed cross-source corroboration" className="rounded-lg border border-blue-400/30 p-3 text-sm leading-6 text-slate-300">
      <p className="font-medium">{corroborationLabels[corroboration.status]}</p>
      <p>{corroboration.supporting_pair_count} reviewed support pairs · {corroboration.refuting_pair_count} reviewed refutation pairs</p>
      <p className="text-xs text-slate-400">Applies only to this claim and the captured evidence inputs. Authenticated operator origin review is part of the basis; NLI confidence is not a probability that the claim is true. No article-wide truth verdict is produced.</p>
      <details className="mt-2 text-xs">
        <summary className="cursor-pointer">Corroboration decision provenance</summary>
        <dl className="mt-2 space-y-1 break-all">
          <dt>Decision policy</dt><dd>{corroboration.policy_version}</dd>
          <dt>Claim SHA-256</dt><dd>{corroboration.claim_sha256}</dd>
          {corroboration.review_scope_sha256s.map(value => <div key={value}><dt>Reviewed evidence scope SHA-256</dt><dd>{value}</dd></div>)}
          {corroboration.review_record_sha256s.map(value => <div key={value}><dt>Authorized record SHA-256</dt><dd>{value}</dd></div>)}
        </dl>
      </details>
    </section>}
    {trusted && <section aria-label="Trusted reporting-origin assessment" className="rounded-lg border border-blue-400/30 p-3 text-xs leading-5 text-slate-300">
      <p className="font-medium">{reviewLabels[trusted.status]}</p>
      <p>{trusted.reviewed_pair_count} reviewed pairs · {trusted.distinct_reporting_pair_count} reviewed as distinct · {trusted.inconclusive_pair_count} inconclusive · {trusted.dependency_documented_pair_count} with documented dependency · {trusted.pending_pair_count} pending · {trusted.unavailable_pair_count} unavailable</p>
      <p className="text-slate-400">This operator assessment applies to the exact claim and evidence inputs shown. It is not a factual truth verdict.</p>
      <details className="mt-2">
        <summary className="cursor-pointer">Authenticated review provenance</summary>
        <dl className="mt-2 space-y-1 break-all">
          <dt>Review policy</dt><dd>{trusted.policy_version}</dd>
          {trusted.pairs.map(pair => <div key={pair.scope_sha256} className="mt-3">
            <dt>Pair assessment</dt><dd>{reviewLabels[pair.decision]}</dd>
            <dt>Left evidence passage</dt><dd>{pair.left_passage_id}</dd>
            <dt>Right evidence passage</dt><dd>{pair.right_passage_id}</dd>
            <dt>Claim and evidence scope SHA-256</dt><dd>{pair.scope_sha256}</dd>
            {pair.record_sha256 && <><dt>Operator record SHA-256</dt><dd>{pair.record_sha256}</dd></>}
            {pair.reviewed_at && <><dt>Reviewed at</dt><dd>{pair.reviewed_at}</dd></>}
            {pair.expires_at && <><dt>Review valid until</dt><dd>{pair.expires_at}</dd></>}
          </div>)}
        </dl>
        <p className="mt-2 text-slate-400">The server checks record authority, scope, expiry and revocation. A record fingerprint supports traceability; it does not authenticate the publisher&apos;s facts.</p>
      </details>
    </section>}
    {audit ? <div className="rounded-lg border border-white/10 p-3 text-xs leading-5 text-slate-300">
      <p className="font-medium">{trusted ? "Automated reporting-origin leads" : "Reporting-origin review · independence not established"}</p>
      <p>{audit.candidate_pair_count} candidate pairs · {audit.dependency_indicated_pair_count} with dependency indicated · {audit.unverified_origin_pair_count} with origin unverified · {audit.unreviewed_pair_count} awaiting review</p>
      <p className="text-slate-400">These counts describe review coverage. They do not certify independent reporting.</p>
    </div> : claim.external_references.length > 0 && <p className="text-xs text-amber-300">Reporting-origin review unavailable. Independence not established.</p>}
    {claim.external_references.length > 0 && <>
      <p className="text-xs font-medium text-slate-400">Captured external source references</p>
      <p className="text-xs text-slate-400">NLI scores measure textual relations, not factual truth probabilities. Admission reflects the server&apos;s evidence review.</p>
      {claim.external_references.map((ref) => (
        <div key={ref.citation_id} className="rounded-lg border border-white/10 p-3 text-sm text-slate-300">
          <p>{isArticleEvidenceUrl(ref.article_url)
            ? <a href={ref.article_url} target="_blank" rel="noopener noreferrer" className="underline decoration-blue-500">{ref.publisher_domain}</a>
            : ref.publisher_domain}</p>
          <p className="mt-1 font-medium">{admissionLabel(ref)}</p>
          <p className="text-xs text-slate-400">{ref.nli_label.toLowerCase()} · NLI score {ref.nli_confidence.toFixed(2)}</p>
          {ref.nli_label === "NEUTRAL" && <p className="mt-1 text-xs text-slate-400">This passage neither supports nor refutes the claim. Its score is confidence in that textual relation.</p>}
          {!!ref.scope_exclusion_codes?.length && <p className="mt-1 text-xs text-amber-300">Review exclusions: {ref.scope_exclusion_codes.join(" · ").replaceAll("_", " ")}</p>}
          <details className="mt-2 text-xs text-slate-400">
            <summary className="cursor-pointer">Evidence provenance</summary>
            <dl className="mt-2 space-y-1 break-all">
              <dt>Input</dt><dd>{ref.input_kind === "DERIVED_PARAGRAPH" ? "Paragraph from captured article" : "Stored passage"}</dd>
              <dt>Citation</dt><dd>{ref.citation_id}</dd>
              <dt>Passage</dt><dd>{ref.passage_id}</dd>
              {ref.document_version_id && <><dt>Document version</dt><dd>{ref.document_version_id}</dd></>}
              {ref.parent_passage_id && <><dt>Parent passage</dt><dd>{ref.parent_passage_id}</dd></>}
              {ref.input_start_offset != null && ref.input_end_offset != null && <><dt>Captured-text offsets (end exclusive)</dt><dd>{ref.input_start_offset}–{ref.input_end_offset}</dd></>}
              {ref.input_sha256 && <><dt>Input SHA-256</dt><dd>{ref.input_sha256}</dd></>}
              {ref.snapshot_sha256 && <><dt>Snapshot SHA-256</dt><dd>{ref.snapshot_sha256}</dd></>}
              {ref.fetch_observation_id && <><dt>Fetch observation</dt><dd>{ref.fetch_observation_id}</dd></>}
            </dl>
            <p className="mt-2">Identifiers and hashes support traceability; they do not authenticate the publisher or establish independence.</p>
          </details>
        </div>
      ))}
    </>}
    {audit && <details className="text-xs text-slate-400">
      <summary className="cursor-pointer">Origin review provenance</summary>
      <dl className="mt-2 space-y-1 break-all">
        <dt>Review policy</dt><dd>{audit.policy_version}</dd>
        <dt>Review packet SHA-256</dt><dd>{audit.review_packet_sha256}</dd>
        <dt>Audit packet SHA-256</dt><dd>{audit.audit_packet_sha256}</dd>
        <dt>Recorded observations</dt><dd>{audit.observations_count}</dd>
        {claim.external_admission_policy_version && <><dt>Admission policy</dt><dd>{claim.external_admission_policy_version}</dd></>}
        {claim.external_audited_parent_count != null && <><dt>Audited parent passages</dt><dd>{claim.external_audited_parent_count}</dd></>}
      </dl>
    </details>}
  </div>;
}
