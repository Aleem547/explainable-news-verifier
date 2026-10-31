
/** Phase 13E.7 preview contract. Keep separate from the generated claim API types. */

export type ArticleVerificationRequest = {
  kind: "pasted";
  text: string;
  title?: string;
};

export interface ArticleEvidenceReference {
  citation_id: string;
  passage_id: string;
  publisher_domain: string;
  article_url: string;
  nli_label: "ENTAILMENT" | "CONTRADICTION" | "NEUTRAL";
  nli_confidence: number;
  independence_status: "NOT_ESTABLISHED";
  claim_id?: string;
  document_version_id?: string;
  nli_threshold_passed?: boolean;
  decisive_evidence_admitted?: boolean | null;
  scope_exclusion_codes?: string[];
  input_kind?: "STORED_PASSAGE" | "DERIVED_PARAGRAPH";
  parent_passage_id?: string | null;
  input_sha256?: string | null;
  input_start_offset?: number | null;
  input_end_offset?: number | null;
  snapshot_sha256?: string | null;
  fetch_observation_id?: string | null;
  dependency_risk_family?: number;
  duplicate_group?: number;
}

export interface ArticleOriginAudit {
  review_packet_sha256: string;
  audit_packet_sha256: string;
  candidate_pair_count: number;
  dependency_indicated_pair_count: number;
  unverified_origin_pair_count: number;
  unreviewed_pair_count: number;
  observations_count: number;
  policy_version: "phase13f-origin-dependency-audit-v2";
}

export interface TrustedOriginPairReview {
  scope_sha256: string;
  left_passage_id: string;
  right_passage_id: string;
  stance: "SUPPORT_ONLY" | "REFUTE_ONLY";
  decision: "PENDING" | "REVIEW_UNAVAILABLE" | "INCONCLUSIVE" | "DEPENDENCY_DOCUMENTED" | "REVIEWED_DISTINCT_REPORTING";
  record_sha256: string | null;
  reviewed_at: string | null;
  expires_at: string | null;
}

export interface TrustedOriginReview {
  policy_version: "trusted-reporting-origin-review-v1";
  status: TrustedOriginPairReview["decision"] | "NO_ELIGIBLE_PAIR";
  candidate_pair_count: number;
  reviewed_pair_count: number;
  distinct_reporting_pair_count: number;
  inconclusive_pair_count: number;
  dependency_documented_pair_count: number;
  pending_pair_count: number;
  unavailable_pair_count: number;
  pairs: TrustedOriginPairReview[];
}

export interface ArticleClaimResult {
  candidate_id: string;
  literal_text: string;
  paragraph_index: number;
  start_char: number;
  end_char: number;
  execution_status: "ASSESSED" | "UNAVAILABLE" | "FAILED" | "SKIPPED_LIMIT";
  wikipedia_status: string | null;
  wikipedia_verdict: string | null;
  wikipedia_supporting_pages: string[];
  wikipedia_refuting_pages: string[];
  external_status: string | null;
  external_verdict: string | null;
  external_references: ArticleEvidenceReference[];
  cross_corpus_relationship: string | null;
  warning_codes: string[];
  independent_corroboration_established: false;
  external_input_kind?: "STORED_PASSAGE" | "DERIVED_PARAGRAPH";
  external_audited_parent_count?: number | null;
  external_origin_audit?: ArticleOriginAudit | null;
  external_admission_policy_version?: string | null;
  external_trusted_origin_review?: TrustedOriginReview | null;
  external_reviewed_corroboration?: ReviewedCorroboration | null;
}

export interface ReviewedCorroboration {
  policy_version: "reviewed-claim-corroboration-v1";
  status: "REVIEWED_SUPPORT" | "REVIEWED_REFUTATION" | "CONFLICTING_EVIDENCE" | "NOT_ESTABLISHED";
  corroboration_established: boolean;
  claim_sha256: string;
  supporting_pair_count: number;
  refuting_pair_count: number;
  review_scope_sha256s: string[];
  review_record_sha256s: string[];
  evidence_passage_ids: string[];
  reason_codes: string[];
}

export interface ArticleVerificationReport {
  article_sha256: string;
  source_kind: "USER_SUPPLIED_ONLY";
  source_url: null;
  assessed_at: string;
  candidate_count: number;
  assessed_count: number;
  unavailable_count: number;
  failed_count: number;
  skipped_count: number;
  claims: ArticleClaimResult[];
  warnings: string[];
  provenance_status: "ARTICLE_INPUT_NOT_INDEPENDENT_EVIDENCE";
  independence_status: "NOT_ESTABLISHED";
  independent_corroboration_established: false;
  overall_article_truth_verdict: null;
  overall_article_truth_probability: null;
}

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const isInteger = (value: unknown, max = 2_000_000): value is number =>
  typeof value === "number" && Number.isSafeInteger(value) && value >= 0 && value <= max;
const isText = (value: unknown, max = 2000): value is string =>
  typeof value === "string" && value.length > 0 && value.length <= max;
const isDigest = (value: unknown): value is string =>
  typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const isUuid = (value: unknown): value is string =>
  typeof value === "string" && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value);
const isNullableText = (value: unknown) => value === null || isText(value);
const isStrings = (value: unknown, max = 80): value is string[] =>
  Array.isArray(value) && value.length <= max && value.every((item: unknown) => isText(item));
const isCodes = (value: unknown): value is string[] =>
  isStrings(value) && value.every((code) => /^[A-Z0-9_]{1,256}$/.test(code)) &&
  new Set(value).size === value.length;
const optional = (value: unknown, check: (v: unknown) => boolean) =>
  value === undefined || check(value);

export function isArticleEvidenceUrl(value: unknown): value is string {
  if (!isText(value, 8192)) return false;
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" && !parsed.username && !parsed.password;
  } catch { return false; }
}

function validOriginAudit(value: unknown, referenceCount: number): boolean {
  if (!isObject(value)) return false;
  const counts = [value.candidate_pair_count, value.dependency_indicated_pair_count,
    value.unverified_origin_pair_count, value.unreviewed_pair_count, value.observations_count];
  if (!counts.every((count): count is number => isInteger(count, 190))) return false;
  const [pairs, dependent, unknown, pending, observations] = counts;
  return pairs === dependent + unknown + pending && observations <= 100 &&
    observations >= dependent + unknown && (pairs !== 0 || observations === 0) &&
    pairs <= referenceCount * (referenceCount - 1) / 2 &&
    value.policy_version === "phase13f-origin-dependency-audit-v2" &&
    isDigest(value.review_packet_sha256) && isDigest(value.audit_packet_sha256);
}

function validTrustedOriginReview(claim: Record<string, unknown>): boolean {
  const value = claim.external_trusted_origin_review;
  if (value == null) return true;
  if (!isObject(value) || claim.external_input_kind !== "DERIVED_PARAGRAPH" ||
      !isObject(claim.external_origin_audit) || !Array.isArray(claim.external_references) ||
      value.policy_version !== "trusted-reporting-origin-review-v1" || !Array.isArray(value.pairs)) return false;
  const keys = ["policy_version", "status", "candidate_pair_count", "reviewed_pair_count",
    "distinct_reporting_pair_count", "inconclusive_pair_count", "dependency_documented_pair_count",
    "pending_pair_count", "unavailable_pair_count", "pairs"];
  if (Object.keys(value).length !== keys.length || !Object.keys(value).every(k => keys.includes(k))) return false;
  const counts = [value.candidate_pair_count, value.reviewed_pair_count, value.distinct_reporting_pair_count,
    value.inconclusive_pair_count, value.dependency_documented_pair_count, value.pending_pair_count,
    value.unavailable_pair_count];
  if (!counts.every((n): n is number => isInteger(n, 190))) return false;
  const [total, reviewed, distinct, inconclusive, dependent, pending, unavailable] = counts;
  if (value.pairs.length !== total || total !== claim.external_origin_audit.candidate_pair_count ||
      reviewed !== distinct + inconclusive + dependent || total !== reviewed + pending + unavailable) return false;
  const refs = new Map<string, Record<string, unknown>>();
  for (const ref of claim.external_references) {
    if (!isObject(ref) || typeof ref.passage_id !== "string") return false;
    refs.set(ref.passage_id, ref);
  }
  const seen = new Set<string>();
  const actual = {REVIEWED_DISTINCT_REPORTING: 0, INCONCLUSIVE: 0, DEPENDENCY_DOCUMENTED: 0, PENDING: 0, REVIEW_UNAVAILABLE: 0};
  for (const pair of value.pairs as unknown[]) {
    const pairKeys = ["scope_sha256", "left_passage_id", "right_passage_id", "stance", "decision",
      "record_sha256", "reviewed_at", "expires_at"];
    if (!isObject(pair) || Object.keys(pair).length !== pairKeys.length ||
        !Object.keys(pair).every(k => pairKeys.includes(k)) || !isDigest(pair.scope_sha256) ||
        seen.has(pair.scope_sha256) || !isUuid(pair.left_passage_id) || !isUuid(pair.right_passage_id) ||
        !["SUPPORT_ONLY", "REFUTE_ONLY"].includes(String(pair.stance)) ||
        !Object.hasOwn(actual, String(pair.decision))) return false;
    const a = refs.get(pair.left_passage_id), b = refs.get(pair.right_passage_id);
    if (!a || !b || !isText(a.publisher_domain) || !isText(b.publisher_domain) ||
        a.publisher_domain >= b.publisher_domain || a.document_version_id === b.document_version_id ||
        !isInteger(a.dependency_risk_family, 20) || !isInteger(b.dependency_risk_family, 20) ||
        a.dependency_risk_family < 1 || b.dependency_risk_family < 1 ||
        a.dependency_risk_family === b.dependency_risk_family ||
        !isInteger(a.duplicate_group, 20) || !isInteger(b.duplicate_group, 20) ||
        a.duplicate_group < 1 || b.duplicate_group < 1 || a.duplicate_group === b.duplicate_group ||
        a.decisive_evidence_admitted !== true || b.decisive_evidence_admitted !== true ||
        a.nli_label !== (pair.stance === "SUPPORT_ONLY" ? "ENTAILMENT" : "CONTRADICTION") ||
        a.nli_label !== b.nli_label) return false;
    const signed = !["PENDING", "REVIEW_UNAVAILABLE"].includes(String(pair.decision));
    if (signed) {
      if (!isDigest(pair.record_sha256) || !isText(pair.reviewed_at, 64) || !isText(pair.expires_at, 64)) return false;
      const issued = Date.parse(pair.reviewed_at), expires = Date.parse(pair.expires_at);
      if (!Number.isFinite(issued) || !Number.isFinite(expires) || expires <= issued ||
          expires - issued > 30 * 24 * 60 * 60 * 1000) return false;
    } else if ([pair.record_sha256, pair.reviewed_at, pair.expires_at].some(x => x !== null)) return false;
    actual[pair.decision as keyof typeof actual]++; seen.add(pair.scope_sha256);
  }
  const status = unavailable ? "REVIEW_UNAVAILABLE" : dependent ? "DEPENDENCY_DOCUMENTED" :
    distinct ? "REVIEWED_DISTINCT_REPORTING" : inconclusive ? "INCONCLUSIVE" : total ? "PENDING" : "NO_ELIGIBLE_PAIR";
  return value.status === status && actual.REVIEWED_DISTINCT_REPORTING === distinct &&
    actual.INCONCLUSIVE === inconclusive && actual.DEPENDENCY_DOCUMENTED === dependent &&
    actual.PENDING === pending && actual.REVIEW_UNAVAILABLE === unavailable;
}

function validReviewedCorroboration(claim: Record<string, unknown>): boolean {
  const value = claim.external_reviewed_corroboration;
  if (value == null) return true; // Historical reports do not invent a new decision.
  const review = claim.external_trusted_origin_review;
  if (!isObject(value) || !isObject(review) || !Array.isArray(review.pairs) ||
      !Array.isArray(claim.external_references) || value.policy_version !== "reviewed-claim-corroboration-v1" ||
      typeof value.corroboration_established !== "boolean" || !isDigest(value.claim_sha256) ||
      !isInteger(value.supporting_pair_count, 190) || !isInteger(value.refuting_pair_count, 190) ||
      !isCodes(value.reason_codes)) return false;
  const keys = ["policy_version", "status", "corroboration_established", "claim_sha256", "supporting_pair_count",
    "refuting_pair_count", "review_scope_sha256s", "review_record_sha256s", "evidence_passage_ids", "reason_codes"];
  if (Object.keys(value).length !== keys.length || !Object.keys(value).every(k => keys.includes(k))) return false;
  const approved = review.pairs.filter((p): p is Record<string, unknown> =>
    isObject(p) && p.decision === "REVIEWED_DISTINCT_REPORTING");
  const support = approved.filter(p => p.stance === "SUPPORT_ONLY").length;
  const refute = approved.filter(p => p.stance === "REFUTE_ONLY").length;
  const admitted = new Set(claim.external_references.filter((r): r is Record<string, unknown> =>
    isObject(r) && r.decisive_evidence_admitted === true).map(r => r.nli_label));
  let status = "NOT_ESTABLISHED", reason = "REVIEWED_PAIRS_AND_ADMITTED_STANCES_NOT_CONSISTENT";
  if (typeof review.unavailable_pair_count === "number" && review.unavailable_pair_count > 0) {
    reason = "CURRENT_ORIGIN_REVIEW_UNAVAILABLE";
  } else if (typeof review.dependency_documented_pair_count === "number" && review.dependency_documented_pair_count > 0) {
    reason = "DOCUMENTED_DEPENDENCY_REQUIRES_RESOLUTION";
  } else if (!approved.length) reason = "NO_CURRENT_DISTINCT_REPORTING_REVIEW";
  else if (admitted.has("ENTAILMENT") && admitted.has("CONTRADICTION")) {
    status = "CONFLICTING_EVIDENCE"; reason = "ADMITTED_COUNTEREVIDENCE_BLOCKS_ONE_SIDED_CORROBORATION";
  } else if (support && !refute && admitted.size === 1 && admitted.has("ENTAILMENT")) {
    status = "REVIEWED_SUPPORT"; reason = "AUTHORIZED_DISTINCT_REPORTING_AND_ADMITTED_SUPPORT";
  } else if (refute && !support && admitted.size === 1 && admitted.has("CONTRADICTION")) {
    status = "REVIEWED_REFUTATION"; reason = "AUTHORIZED_DISTINCT_REPORTING_AND_ADMITTED_REFUTATION";
  }
  const same = (actual: unknown, expected: unknown[]) => Array.isArray(actual) &&
    JSON.stringify(actual) === JSON.stringify(expected);
  const reasons = ["CLAIM_SCOPED_TEXTUAL_CORROBORATION", "NO_ARTICLE_WIDE_TRUTH_VERDICT",
    "NLI_CONFIDENCE_IS_NOT_FACTUAL_TRUTH_PROBABILITY", reason].sort();
  return value.status === status && value.corroboration_established === ["REVIEWED_SUPPORT", "REVIEWED_REFUTATION"].includes(status) &&
    value.supporting_pair_count === support && value.refuting_pair_count === refute &&
    same(value.review_scope_sha256s, approved.map(p => p.scope_sha256).sort()) &&
    same(value.review_record_sha256s, approved.map(p => p.record_sha256).sort()) &&
    same(value.evidence_passage_ids, [...new Set(approved.flatMap(p => [p.left_passage_id, p.right_passage_id]))].sort()) &&
    same(value.reason_codes, reasons);
}

function validExternalEvidence(claim: Record<string, unknown>): boolean {
  const refs = claim.external_references;
  if (!Array.isArray(refs) || refs.length > 20) return false;
  const kind = claim.external_input_kind ?? "STORED_PASSAGE";
  if (claim.external_input_kind === null || !["STORED_PASSAGE", "DERIVED_PARAGRAPH"].includes(String(kind))) return false;
  const derived = kind === "DERIVED_PARAGRAPH";
  if (!optional(claim.external_admission_policy_version, (v) => v === null || isText(v, 128))) return false;
  if (derived) {
    if (claim.external_status !== "AVAILABLE" || !isInteger(claim.external_audited_parent_count, 20) ||
        claim.external_audited_parent_count < 2 || !isText(claim.external_admission_policy_version, 128) ||
        !validOriginAudit(claim.external_origin_audit, refs.length)) return false;
  } else if (claim.external_audited_parent_count != null) return false;
  if (claim.external_origin_audit != null && !validOriginAudit(claim.external_origin_audit, refs.length)) return false;

  const citations = new Set<string>();
  const passages = new Set<string>();
  const versions = new Set<string>();
  const parents = new Map<string, string>();
  for (const ref of refs as unknown[]) {
    if (!isObject(ref) || !isText(ref.citation_id, 256) || citations.has(ref.citation_id) ||
        !isText(ref.passage_id, 256) || passages.has(ref.passage_id.toLowerCase()) ||
        !isText(ref.publisher_domain, 253) || !isArticleEvidenceUrl(ref.article_url) ||
        !(ref.independence_status === "NOT_ESTABLISHED") ||
        typeof ref.nli_confidence !== "number" || !Number.isFinite(ref.nli_confidence) ||
        ref.nli_confidence < 0 || ref.nli_confidence > 1 ||
        !["ENTAILMENT", "CONTRADICTION", "NEUTRAL"].includes(String(ref.nli_label)) ||
        !optional(ref.nli_threshold_passed, (v) => typeof v === "boolean") ||
        !optional(ref.decisive_evidence_admitted, (v) => v === null || typeof v === "boolean") ||
        !optional(ref.scope_exclusion_codes, isCodes) ||
        !optional(ref.input_sha256, (v) => v === null || isDigest(v)) ||
        !optional(ref.claim_id, (v) => v === claim.candidate_id) ||
        !optional(ref.document_version_id, isUuid) ||
        ref.input_kind === null || (ref.input_kind ?? "STORED_PASSAGE") !== kind) return false;
    citations.add(ref.citation_id); passages.add(ref.passage_id.toLowerCase());
    // A high NLI score alone never establishes admission or independence.
    if (ref.decisive_evidence_admitted === true && (ref.nli_threshold_passed !== true ||
        ref.nli_label === "NEUTRAL" || !isCodes(ref.scope_exclusion_codes) || ref.scope_exclusion_codes.length > 0)) return false;
    if (derived) {
      if (!isUuid(ref.passage_id) || !isUuid(ref.document_version_id) || ref.claim_id !== claim.candidate_id ||
          !isUuid(ref.parent_passage_id) || ref.parent_passage_id.toLowerCase() === ref.passage_id.toLowerCase() ||
          !isUuid(ref.fetch_observation_id) || !isDigest(ref.input_sha256) || !isDigest(ref.snapshot_sha256) ||
          typeof ref.decisive_evidence_admitted !== "boolean" || typeof ref.nli_threshold_passed !== "boolean" ||
          !isCodes(ref.scope_exclusion_codes) || !isInteger(ref.input_start_offset) ||
          !isInteger(ref.input_end_offset) || ref.input_end_offset <= ref.input_start_offset) return false;
      const identity = JSON.stringify([ref.document_version_id.toLowerCase(), ref.publisher_domain,
        ref.article_url, ref.snapshot_sha256, ref.fetch_observation_id.toLowerCase()]);
      const parent = ref.parent_passage_id.toLowerCase();
      if (parents.has(parent) && parents.get(parent) !== identity) return false;
      parents.set(parent, identity); versions.add(ref.document_version_id.toLowerCase());
    } else if ([ref.parent_passage_id, ref.input_start_offset, ref.input_end_offset,
        ref.snapshot_sha256, ref.fetch_observation_id].some((v) => v != null)) return false;
  }
  return validTrustedOriginReview(claim) && validReviewedCorroboration(claim) && (!derived || (parents.size >= 2 && versions.size >= 2 &&
    parents.size <= (claim.external_audited_parent_count as number)));
}

/** Check the public presentation contract, not authenticity of source snapshots. */
export function isArticleVerificationReport(value: unknown): value is ArticleVerificationReport {
  if (!isObject(value) || !Array.isArray(value.claims) || value.claims.length > 50 ||
      value.source_kind !== "USER_SUPPLIED_ONLY" || value.source_url !== null ||
      value.provenance_status !== "ARTICLE_INPUT_NOT_INDEPENDENT_EVIDENCE" ||
      value.independence_status !== "NOT_ESTABLISHED" || value.independent_corroboration_established !== false ||
      !optional(value.independently_verified, (v) => v === false) ||
      !optional(value.eligible_as_independent_evidence, (v) => v === false) ||
      value.overall_article_truth_verdict !== null || value.overall_article_truth_probability !== null ||
      !isDigest(value.article_sha256) || !isText(value.assessed_at, 128) || !Number.isFinite(Date.parse(value.assessed_at)) ||
      value.candidate_count !== value.claims.length || !isCodes(value.warnings)) return false;
  const counts = [value.assessed_count, value.unavailable_count, value.failed_count, value.skipped_count];
  if (!counts.every((n): n is number => isInteger(n, 50)) ||
      counts.reduce((a, b) => a + b, 0) !== value.candidate_count) return false;
  const statuses = ["ASSESSED", "UNAVAILABLE", "FAILED", "SKIPPED_LIMIT"];
  const actualCounts = [0, 0, 0, 0];
  const ids = new Set<string>();
  for (const claim of value.claims as unknown[]) {
    if (!isObject(claim) || !isText(claim.candidate_id, 256) || ids.has(claim.candidate_id) ||
        !isText(claim.literal_text) || !isInteger(claim.paragraph_index) || !isInteger(claim.start_char) ||
        !isInteger(claim.end_char) || claim.end_char <= claim.start_char ||
        !(claim.independent_corroboration_established === false) || !isCodes(claim.warning_codes) ||
        !isNullableText(claim.wikipedia_status) || !isNullableText(claim.wikipedia_verdict) ||
        !isNullableText(claim.external_status) || !isNullableText(claim.external_verdict) ||
        !isNullableText(claim.cross_corpus_relationship) || !isStrings(claim.wikipedia_supporting_pages) ||
        !isStrings(claim.wikipedia_refuting_pages) || !validExternalEvidence(claim)) return false;
    const index = statuses.indexOf(String(claim.execution_status));
    if (index === -1) return false;
    actualCounts[index]++; ids.add(claim.candidate_id);
  }
  return counts.every((n, index) => n === actualCounts[index]);
}
