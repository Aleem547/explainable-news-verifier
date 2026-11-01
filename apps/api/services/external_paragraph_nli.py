"""Opt-in paragraph NLI over freshly audited parent passages; read only.

All database audit/dependency calls receive original stored candidates. Only
derived paragraph text is sent to the predictor and to pure normalization.
"""

from datetime import UTC, datetime

from apps.api.services.external_evidence_nli import (
    ExternalNliError, _validate_request, build_external_nli_report,
)
from ml.verification.paragraph_inputs import selection_from_audits, AuditedParagraphInput, parent_matches_candidate


def _predict_checked(claim, texts, predictor):
    if predictor is None:
        from apps.api.services.multisource import _load_model, _model_lock, _model_predict
        with _model_lock:
            model = _load_model()
        predict = _model_predict
    else:
        model, predict = predictor, predictor.predict
    maximum = getattr(model, "max_length", None)
    if type(maximum) is not int or not 16 <= maximum <= 4096:
        raise ExternalNliError("paragraph_predictor_requires_token_budget")
    lengths = model.tokenizer(texts, [claim]*len(texts), padding=False,
                              truncation=False, return_length=True)["length"]
    if (len(lengths) != len(texts)
            or any(type(n) is not int or not 0 < n <= maximum for n in lengths)):
        raise ExternalNliError("paragraph_input_would_be_truncated_or_invalid")
    return predict(claim, texts), tuple(lengths), maximum


async def assess_external_paragraph_nli(
    session, *, claim, candidates, assessed_at=None, nli_threshold=0.90,
    selection_claim=None, predictor=None, reported_links=(), expected_selection=None,
    max_inputs=20,
):
    """Server-only entry point; public request data must not supply policies.

    selection_claim freezes the same input set across diagnostic probes. It is
    not a score-based selection override. Ordinary use selects with claim.
    Parents are re-audited on each call, including full source dependency checks.
    """
    from apps.api.services.external_evidence_provenance import audit_external_passage_provenance
    from apps.api.services.external_source_independence import audit_external_source_dependencies
    from apps.api.services.external_evidence_normalization import normalize_and_group_external_evidence
    from starlette.concurrency import run_in_threadpool
    at = assessed_at or datetime.now(UTC)
    _validate_request(claim, candidates, nli_threshold, at)
    if type(max_inputs) is not int or not 2 <= max_inputs <= 20:
        raise ExternalNliError("invalid_paragraph_input_budget")
    if not isinstance(reported_links, (tuple, list)) or len(reported_links) > 100:
        raise ExternalNliError("invalid_reported_dependency_batch")
    parents = tuple(candidates)
    audits = await audit_external_passage_provenance(session, parents)
    selection = selection_from_audits(audits, selection_claim if selection_claim is not None else claim)
    # Reject the complete selection before model loading. Do not silently trim
    # contexts, lose an article, or fall back to potentially truncated passages.
    if len(selection.inputs) > max_inputs:
        raise ExternalNliError("paragraph_input_budget_exceeded")
    if expected_selection is not None and selection != expected_selection:
        raise ExternalNliError("paragraph_selection_changed_before_prediction")
    by_parent = {p.passage_id: p for p in selection.parents}
    if (len(by_parent) != len(parents)
            or {p.passage_id for p in parents} != set(by_parent)
            or any(not parent_matches_candidate(by_parent[p.passage_id], p) for p in parents)
            or any(p.fetch_observed_at > at or p.retrieved_at > at for p in selection.parents)):
        raise ExternalNliError("paragraph_audit_parent_or_time_mismatch")
    normalized = normalize_and_group_external_evidence(list(selection.inputs))
    if reported_links:
        risks = await audit_external_source_dependencies(
            session, parents, assessed_at=at, reported_links=tuple(reported_links))
    else:
        risks = await audit_external_source_dependencies(session, parents, assessed_at=at)
    predictions, lengths, maximum = await run_in_threadpool(
        _predict_checked, claim.strip(), [p.text for p in selection.inputs], predictor)
    report = build_external_nli_report(
        claim=claim, audits=tuple(AuditedParagraphInput(p) for p in selection.inputs),
        normalization=normalized, dependencies=risks, predictions=predictions,
        assessed_at=at, nli_threshold=nli_threshold,
        paragraph_selection=selection, input_pair_tokens=lengths, model_max_length=maximum,
    )
    from dataclasses import replace
    warnings = set(report.warnings) | {
        "DERIVED_PARAGRAPH_IDS_ARE_NOT_DATABASE_PASSAGE_IDS",
        "PARAGRAPH_BOUNDARIES_ARE_NOT_PROOF_OF_SEMANTIC_COMPLETENESS",
    }
    if reported_links:
        warnings.update(set(risks.warnings) - {"NO_NLI_OR_TRUTH_ASSESSMENT"})
        warnings.add("REPORTED_DEPENDENCIES_ARE_UNAUTHENTICATED_DECLARATIONS")
    return replace(report, warnings=tuple(sorted(warnings)))
