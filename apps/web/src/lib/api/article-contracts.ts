
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

const isObject = (
  value: unknown
): value is Record<string, unknown> =>
  typeof value === "object" &&
  value !== null &&
  !Array.isArray(value);

/** Validate key integrity constraints before displaying external references. */
export function isArticleVerificationReport(
  value: unknown
): value is ArticleVerificationReport {
  if (
    !isObject(value) ||
    !Array.isArray(value.claims) ||
    value.claims.length > 50
  ) {
    return false;
  }

  if (
    value.source_kind !== "USER_SUPPLIED_ONLY" ||
    value.source_url !== null ||
    value.provenance_status !== "ARTICLE_INPUT_NOT_INDEPENDENT_EVIDENCE" ||
    value.independence_status !== "NOT_ESTABLISHED" ||
    value.independent_corroboration_established !== false ||
    value.overall_article_truth_verdict !== null ||
    value.overall_article_truth_probability !== null ||
    typeof value.article_sha256 !== "string" ||
    !/^[a-f0-9]{64}$/.test(value.article_sha256) ||
    typeof value.candidate_count !== "number" ||
    !Number.isSafeInteger(value.candidate_count) ||
    value.candidate_count !== value.claims.length ||
    !Array.isArray(value.warnings) ||
    !value.warnings.every(
      (warning: unknown) => typeof warning === "string"
    )
  ) {
    return false;
  }

  const counts = [
    value.assessed_count,
    value.unavailable_count,
    value.failed_count,
    value.skipped_count,
  ];

  // Narrow unknown values to verified integers before summing.
  if (
    !counts.every(
      (n): n is number =>
        typeof n === "number" &&
        Number.isSafeInteger(n) &&
        n >= 0
    )
  ) {
    return false;
  }

  if (
    counts.reduce((a, b) => a + b, 0) !==
    value.candidate_count
  ) {
    return false;
  }

  return value.claims.every((claim: unknown) => {
    if (
      !isObject(claim) ||
      !Array.isArray(claim.external_references) ||
      claim.external_references.length > 20
    ) {
      return false;
    }

    return (
      typeof claim.candidate_id === "string" &&
      typeof claim.literal_text === "string" &&
      claim.literal_text.length <= 2000 &&
      typeof claim.start_char === "number" &&
      Number.isSafeInteger(claim.start_char) &&
      claim.start_char >= 0 &&
      typeof claim.end_char === "number" &&
      Number.isSafeInteger(claim.end_char) &&
      claim.end_char > claim.start_char &&
      [
        "ASSESSED",
        "UNAVAILABLE",
        "FAILED",
        "SKIPPED_LIMIT",
      ].includes(String(claim.execution_status)) &&
      claim.independent_corroboration_established === false &&
      Array.isArray(claim.warning_codes) &&
      claim.external_references.every((ref: unknown) =>
        isObject(ref) &&
        typeof ref.citation_id === "string" &&
        typeof ref.publisher_domain === "string" &&
        typeof ref.article_url === "string" &&
        /^https:\/\//.test(ref.article_url) &&
        ref.independence_status === "NOT_ESTABLISHED" &&
        typeof ref.nli_confidence === "number" &&
        Number.isFinite(ref.nli_confidence) &&
        ref.nli_confidence >= 0 &&
        ref.nli_confidence <= 1 &&
        [
          "ENTAILMENT",
          "CONTRADICTION",
          "NEUTRAL",
        ].includes(String(ref.nli_label))
      )
    );
  });
}
