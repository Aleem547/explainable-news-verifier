"""Read-only, bounded retrieval of usable parents for complete paragraph NLI.

Lexical rank and existing subject/boundary rules select inputs before NLI. They
do not establish support, independence or source truth. All pool candidates are
provenance-audited, and selected parents are re-audited by the NLI service.
"""
from ml.verification.paragraph_inputs import (
    ParagraphInputError, choose_audited_paragraph_candidates,
)


async def retrieve_external_paragraph_parents(session, *, claim, top_k=4, candidate_limit=60):
    if (type(top_k) is not int or not 2 <= top_k <= 20
            or type(candidate_limit) is not int or not 20 <= candidate_limit <= 100):
        raise ParagraphInputError("invalid_paragraph_retrieval_budget")
    from apps.api.services.external_passage_retrieval import retrieve_external_passages
    from apps.api.services.external_evidence_provenance import audit_external_passage_provenance
    pool=tuple(await retrieve_external_passages(
        session, claim=claim, top_k=20, candidate_limit=candidate_limit))
    if len(pool) < 2:
        return ()
    if len(pool) > 20:
        raise ParagraphInputError("invalid_parent_audit_batch")
    audits=await audit_external_passage_provenance(session, pool)
    # The auditor promises order and identity; verify those bindings here too.
    if (len(audits) != len(pool)
            or any(audit.candidate != candidate for audit,candidate in zip(audits,pool,strict=True))):
        raise ParagraphInputError("paragraph_retrieval_audit_binding_mismatch")
    return choose_audited_paragraph_candidates(
        audits, claim, max_parents=top_k, max_inputs=top_k)
