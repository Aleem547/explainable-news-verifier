const oldCodes = [
  "CORROBORATION_DECISION_DEFERRED_TO_PHASE_13D7",
  "NO_INDEPENDENT_CORROBORATION_CLAIM",
  "NLI_OUTPUT_IS_NOT_A_FACTUAL_TRUTH_PROBABILITY",
  "REPORTING_ORIGIN_PAIRS_NOT_REVIEWED",
  "UNRECOGNIZED_FUTURE_WARNING_CODE",
];

function makeReport(state = "support") {
  const uuid = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
  const refute = state === "refute";
  const label = refute ? "CONTRADICTION" : "ENTAILMENT";
  const refs = ["isro.gov.in", "www.nasa.gov"].map((domain, i) => ({
    citation_id: `example-${i}`, claim_id: "example-claim", passage_id: uuid(i + 1),
    document_version_id: uuid(i + 10), publisher_domain: domain,
    article_url: `https://${domain}/example`, nli_label: label, nli_confidence: 0.95,
    nli_threshold_passed: true, decisive_evidence_admitted: true, scope_exclusion_codes: [],
    independence_status: "NOT_ESTABLISHED", input_kind: "DERIVED_PARAGRAPH",
    parent_passage_id: uuid(i + 20), input_sha256: "a".repeat(64),
    snapshot_sha256: "b".repeat(64), fetch_observation_id: uuid(i + 30),
    input_start_offset: 0, input_end_offset: 100, dependency_risk_family: i + 1, duplicate_group: i + 1,
  }));
  refs.push({ ...refs[1], citation_id: "example-neutral", passage_id: uuid(3),
    nli_label: state === "conflicting" ? "CONTRADICTION" : "NEUTRAL", nli_confidence: 0.91,
    decisive_evidence_admitted: state === "conflicting", input_start_offset: 100, input_end_offset: 200 });
  const approved = ["support", "refute", "conflicting"].includes(state);
  const unavailable = state === "unavailable";
  const pair = {
    scope_sha256: "c".repeat(64), left_passage_id: refs[0].passage_id, right_passage_id: refs[1].passage_id,
    stance: refute ? "REFUTE_ONLY" : "SUPPORT_ONLY",
    decision: approved ? "REVIEWED_DISTINCT_REPORTING" : unavailable ? "REVIEW_UNAVAILABLE" : "PENDING",
    record_sha256: approved ? "d".repeat(64) : null,
    reviewed_at: approved ? "2026-11-02T00:00:00Z" : null,
    expires_at: approved ? "2026-11-09T00:00:00Z" : null,
  };
  const reason = state === "conflicting" ? "ADMITTED_COUNTEREVIDENCE_BLOCKS_ONE_SIDED_CORROBORATION"
    : approved ? refute ? "AUTHORIZED_DISTINCT_REPORTING_AND_ADMITTED_REFUTATION" : "AUTHORIZED_DISTINCT_REPORTING_AND_ADMITTED_SUPPORT"
    : unavailable ? "CURRENT_ORIGIN_REVIEW_UNAVAILABLE" : "NO_CURRENT_DISTINCT_REPORTING_REVIEW";
  const claim = {
    candidate_id: "example-claim", literal_text: "Chandrayaan-3 landed on the Moon.",
    paragraph_index: 0, start_char: 0, end_char: 31, execution_status: "ASSESSED",
    wikipedia_status: "AVAILABLE", wikipedia_verdict: "SUPPORTING_EVIDENCE",
    wikipedia_supporting_pages: ["Chandrayaan-3"], wikipedia_refuting_pages: [],
    external_status: "AVAILABLE", external_verdict: refute ? "PROVISIONAL_REFUTATION" : "PROVISIONAL_SUPPORT",
    external_references: refs, cross_corpus_relationship: "BOTH_SUPPORT", warning_codes: [...oldCodes],
    independent_corroboration_established: false, external_input_kind: "DERIVED_PARAGRAPH",
    external_audited_parent_count: 2, external_admission_policy_version: "example-policy",
    external_origin_audit: {
      review_packet_sha256: "e".repeat(64), audit_packet_sha256: "f".repeat(64),
      candidate_pair_count: 1, dependency_indicated_pair_count: 0, unverified_origin_pair_count: 0,
      unreviewed_pair_count: 1, observations_count: 0, policy_version: "phase13f-origin-dependency-audit-v2",
    },
    external_trusted_origin_review: {
      policy_version: "trusted-reporting-origin-review-v1",
      status: pair.decision, candidate_pair_count: 1, reviewed_pair_count: approved ? 1 : 0,
      distinct_reporting_pair_count: approved ? 1 : 0, inconclusive_pair_count: 0,
      dependency_documented_pair_count: 0, pending_pair_count: !approved && !unavailable ? 1 : 0,
      unavailable_pair_count: unavailable ? 1 : 0, pairs: [pair],
    },
    external_reviewed_corroboration: {
      policy_version: "reviewed-claim-corroboration-v1",
      status: state === "conflicting" ? "CONFLICTING_EVIDENCE" : approved ? refute ? "REVIEWED_REFUTATION" : "REVIEWED_SUPPORT" : "NOT_ESTABLISHED",
      corroboration_established: approved && state !== "conflicting", claim_sha256: "a".repeat(64),
      supporting_pair_count: approved && !refute ? 1 : 0, refuting_pair_count: approved && refute ? 1 : 0,
      review_scope_sha256s: approved ? [pair.scope_sha256] : [],
      review_record_sha256s: approved ? [pair.record_sha256] : [],
      evidence_passage_ids: approved ? [refs[0].passage_id, refs[1].passage_id].sort() : [],
      reason_codes: ["CLAIM_SCOPED_TEXTUAL_CORROBORATION", "NO_ARTICLE_WIDE_TRUTH_VERDICT",
        "NLI_CONFIDENCE_IS_NOT_FACTUAL_TRUTH_PROBABILITY", reason].sort(),
    },
  };
  if (["insufficient", "legacy"].includes(state)) {
    for (const key of ["external_origin_audit", "external_trusted_origin_review", "external_reviewed_corroboration",
      "external_audited_parent_count", "external_admission_policy_version"]) delete claim[key];
    claim.external_references = [];
    claim.external_input_kind = "STORED_PASSAGE";
    claim.external_verdict = state === "insufficient" ? "INSUFFICIENT_STORED_EVIDENCE" : null;
  }
  return {
    article_sha256: "a".repeat(64), source_kind: "USER_SUPPLIED_ONLY", source_url: null,
    assessed_at: "2026-11-02T12:00:00Z", candidate_count: 1, assessed_count: 1,
    unavailable_count: 0, failed_count: 0, skipped_count: 0, claims: [claim], warnings: [],
    provenance_status: "ARTICLE_INPUT_NOT_INDEPENDENT_EVIDENCE", independence_status: "NOT_ESTABLISHED",
    independent_corroboration_established: false, overall_article_truth_verdict: null, overall_article_truth_probability: null,
  };
}

module.exports = { makeReport, oldCodes };
