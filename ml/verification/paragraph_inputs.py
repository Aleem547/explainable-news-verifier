"""Immutable model inputs derived from freshly audited stored parent spans.

Context IDs are derived evidence IDs, never database passage IDs. Hashes bind
integrity, not publisher authentication or independent reporting.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from hashlib import sha256
import json
import math
from uuid import UUID, NAMESPACE_URL, uuid5

from ml.ingestion.passages import PassageSpan, extract_paragraph_contexts, CONTEXT_POLICY_VERSION
from ml.verification.external_admissibility import external_subject_grounded

SELECTION_POLICY = "phase3.10-audited-parent-paragraphs-v1"


class ParagraphInputError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ParentPassageBinding:
    passage_id: UUID
    document_id: UUID
    document_version_id: UUID
    source_id: UUID
    publisher_name: str
    publisher_domain: str
    original_url: str
    retrieved_at: datetime
    passage_text: str
    passage_sha256: str
    start_offset: int
    end_offset: int
    snapshot_sha256: str
    snapshot_text_length: int
    snapshot_version_number: int
    fetch_observation_id: UUID
    fetch_observed_at: datetime
    lexical_relevance_score: float
    fetch_html_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class ParagraphInput:
    parent: ParentPassageBinding
    start_offset: int
    end_offset: int
    text: str
    sha256: str
    rank: int
    policy_version: str = CONTEXT_POLICY_VERSION

    @property
    def context_id(self):
        payload = [SELECTION_POLICY, self.policy_version, str(self.parent.passage_id),
                   str(self.parent.document_id), str(self.parent.document_version_id),
                   str(self.parent.source_id), self.parent.original_url,
                   self.parent.snapshot_sha256, self.parent.passage_sha256,
                   self.start_offset, self.end_offset, self.sha256]
        return uuid5(NAMESPACE_URL, json.dumps(payload, separators=(",", ":"), ensure_ascii=False))

    # Interface used only by pure normalization/report construction. The
    # provenance SQL auditor rejects this type as a stored passage candidate.
    @property
    def passage_id(self): return self.context_id
    @property
    def document_id(self): return self.parent.document_id
    @property
    def document_version_id(self): return self.parent.document_version_id
    @property
    def source_id(self): return self.parent.source_id
    @property
    def publisher_name(self): return self.parent.publisher_name
    @property
    def publisher_domain(self): return self.parent.publisher_domain
    @property
    def original_url(self): return self.parent.original_url
    @property
    def retrieved_at(self): return self.parent.retrieved_at
    @property
    def passage_text(self): return self.text
    @property
    def passage_sha256(self): return self.sha256
    @property
    def lexical_relevance_score(self): return self.parent.lexical_relevance_score
    @property
    def independently_verified(self): return False
    @property
    def independent_corroboration_established(self): return False
    @property
    def nli_evaluated(self): return False


@dataclass(frozen=True, slots=True)
class ParagraphSelection:
    claim: str
    parents: tuple[ParentPassageBinding, ...]
    inputs: tuple[ParagraphInput, ...]
    exclusions: tuple[tuple[UUID, int, int, tuple[str, ...]], ...]
    policy_version: str = SELECTION_POLICY

    @property
    def selection_sha256(self):
        payload = {
            "policy": self.policy_version, "claim": self.claim,
            "parents": [[str(p.passage_id), str(p.document_id), str(p.document_version_id),
                         str(p.source_id), p.publisher_name, p.publisher_domain, p.original_url,
                         p.retrieved_at.isoformat(), p.passage_sha256, p.start_offset, p.end_offset,
                         p.snapshot_sha256, p.snapshot_text_length, p.snapshot_version_number,
                         str(p.fetch_observation_id), p.fetch_observed_at.isoformat(),
                         p.lexical_relevance_score, p.fetch_html_sha256] for p in self.parents],
            "inputs": [[str(p.context_id), p.rank, str(p.parent.passage_id),
                        p.start_offset, p.end_offset, p.sha256, p.policy_version] for p in self.inputs],
            "excluded": [[str(pid), start, end, list(codes)] for pid, start, end, codes in self.exclusions],
        }
        return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _aware(value):
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def validate_parent(parent):
    if type(parent) is not ParentPassageBinding:
        raise ParagraphInputError("invalid_parent_binding")
    # PostgreSQL drivers may return UUID subclasses. Preserve their values
    # and identity semantics while still rejecting strings and duck types.
    if not all(isinstance(value, UUID) for value in (
            parent.passage_id, parent.document_id, parent.document_version_id,
            parent.source_id, parent.fetch_observation_id)):
        raise ParagraphInputError("invalid_parent_identity")
    if (not isinstance(parent.passage_text, str) or not 1 <= len(parent.passage_text) <= 4000
            or sha256(parent.passage_text.encode()).hexdigest() != parent.passage_sha256
            or type(parent.start_offset) is not int or type(parent.end_offset) is not int
            or type(parent.snapshot_text_length) is not int
            or not 0 <= parent.start_offset < parent.end_offset <= parent.snapshot_text_length <= 2_000_000
            or len(parent.passage_text) != parent.end_offset-parent.start_offset
            or type(parent.snapshot_version_number) is not int or parent.snapshot_version_number < 1
            or not _aware(parent.retrieved_at) or not _aware(parent.fetch_observed_at)
            or type(parent.lexical_relevance_score) not in (int, float)
            or not math.isfinite(parent.lexical_relevance_score) or parent.lexical_relevance_score <= 0
            or not isinstance(parent.snapshot_sha256, str) or len(parent.snapshot_sha256) != 64
            or any(c not in "0123456789abcdef" for c in parent.snapshot_sha256)):
        raise ParagraphInputError("invalid_parent_provenance")
    if (not isinstance(parent.publisher_name, str) or not parent.publisher_name.strip()
            or not isinstance(parent.publisher_domain, str) or not parent.publisher_domain
            or not isinstance(parent.original_url, str) or not parent.original_url.startswith("https://")):
        raise ParagraphInputError("invalid_parent_source")
    if parent.fetch_html_sha256 is not None and (not isinstance(parent.fetch_html_sha256, str)
            or len(parent.fetch_html_sha256) != 64
            or any(c not in "0123456789abcdef" for c in parent.fetch_html_sha256)):
        raise ParagraphInputError("invalid_parent_fetch_html_digest")


def _paragraphs(parent):
    validate_parent(parent)
    # The legacy helper needs a local ordinal; it is not a source ordinal and
    # is deliberately not exported. Parent identity is the audited database UUID.
    span = PassageSpan(0, parent.start_offset, parent.end_offset,
                       parent.passage_text, parent.passage_sha256)
    return extract_paragraph_contexts(span, document_length=parent.snapshot_text_length)


def validate_paragraph_input(value):
    if type(value) is not ParagraphInput or type(value.rank) is not int or value.rank < 1:
        raise ParagraphInputError("invalid_paragraph_input")
    paragraphs = _paragraphs(value.parent)
    if (value.policy_version != CONTEXT_POLICY_VERSION or not any(
            (p.start_offset, p.end_offset, p.text, p.sha256)
            == (value.start_offset, value.end_offset, value.text, value.sha256)
            for p in paragraphs.contexts)):
        raise ParagraphInputError("paragraph_not_bound_to_complete_parent_context")
    if value.context_id == value.parent.passage_id:
        raise ParagraphInputError("derived_identity_must_not_equal_parent")


def _select(parents, claim):
    if not isinstance(claim, str) or not 3 <= len(claim.strip()) <= 2000:
        raise ParagraphInputError("invalid_selection_claim")
    if type(parents) is not tuple or not 2 <= len(parents) <= 20:
        raise ParagraphInputError("invalid_parent_batch")
    for parent in parents:
        validate_parent(parent)
    if len({p.passage_id for p in parents}) != len(parents):
        raise ParagraphInputError("duplicate_parent_passage")
    parents = tuple(sorted(parents, key=lambda p: p.passage_id.hex))
    inputs, excluded = [], []
    for parent in parents:
        paragraphs = _paragraphs(parent)
        excluded.extend((parent.passage_id, p.start_offset, p.end_offset, p.reasons)
                        for p in paragraphs.excluded)
        for paragraph in paragraphs.contexts:
            if external_subject_grounded(claim, paragraph.text):
                inputs.append(ParagraphInput(parent, paragraph.start_offset, paragraph.end_offset,
                                             paragraph.text, paragraph.sha256, 1))
            else:
                excluded.append((parent.passage_id, paragraph.start_offset, paragraph.end_offset,
                                 ("SUBJECT_UNGROUNDED_PARAGRAPH",)))
    if not 2 <= len(inputs) <= 20:
        raise ParagraphInputError("bounded_paragraph_input_count_not_available")
    if {p.document_version_id for p in inputs} != {p.document_version_id for p in parents}:
        raise ParagraphInputError("paragraphs_do_not_cover_all_audited_versions")
    if len({p.document_version_id for p in inputs}) < 2:
        raise ParagraphInputError("two_audited_versions_required")
    inputs.sort(key=lambda p: (p.publisher_domain, p.document_version_id.hex,
                               p.start_offset, p.end_offset, p.parent.passage_id.hex))
    inputs = tuple(replace(p, rank=index) for index, p in enumerate(inputs, 1))
    if len({p.context_id for p in inputs}) != len(inputs):
        raise ParagraphInputError("duplicate_derived_context_identity")
    return ParagraphSelection(claim.strip(), parents, inputs, tuple(sorted(
        excluded, key=lambda p: (p[0].hex, p[1], p[2], p[3]))))


def validate_paragraph_selection(selection):
    if type(selection) is not ParagraphSelection or selection != _select(selection.parents, selection.claim):
        raise ParagraphInputError("paragraph_selection_replay_mismatch")


def parents_from_audits(audits):
    """Validate and retain every audited parent before any context selection."""
    if not isinstance(audits, (list, tuple)) or not 2 <= len(audits) <= 20:
        raise ParagraphInputError("invalid_parent_audit_batch")
    parents = []
    for audit in audits:
        candidate = audit.candidate
        if (getattr(audit, "traceable", None) is not True
                or any(getattr(audit, k, None) is not False for k in
                       ("nli_evaluated", "independently_verified", "independent_corroboration_established"))
                or any(getattr(candidate, k, None) is not False for k in
                       ("nli_evaluated", "independently_verified", "independent_corroboration_established"))):
            raise ParagraphInputError("parent_audit_not_unverified_traceable")
        parents.append(ParentPassageBinding(
            candidate.passage_id, candidate.document_id, candidate.document_version_id,
            candidate.source_id, candidate.publisher_name, candidate.publisher_domain,
            candidate.original_url, candidate.retrieved_at, candidate.passage_text,
            candidate.passage_sha256, audit.passage_start_offset, audit.passage_end_offset,
            audit.snapshot_sha256, audit.snapshot_text_length, audit.snapshot_version_number,
            audit.fetch_observation_id, audit.fetch_observed_at, candidate.lexical_relevance_score,
            fetch_html_sha256=getattr(audit, "fetch_html_sha256", None),
        ))
    for parent in parents:
        validate_parent(parent)
    return tuple(parents)


def selection_from_audits(audits, claim):
    return _select(parents_from_audits(audits), claim)


def choose_audited_paragraph_candidates(audits, claim, *, max_parents=4, max_inputs=4):
    """Choose a bounded, version-diverse parent set before seeing NLI scores.

    Inspect all supplied audits. Only parents containing complete subject-grounded
    contexts qualify. Select the best-ranked feasible pair from two snapshots,
    then fill spare capacity in retrieval order. Each selected parent's complete
    subject-grounded context set must fit; never trim contexts to make it fit.
    An empty result means there is no feasible two-snapshot set in this pool.
    """
    if (type(max_parents) is not int or not 2 <= max_parents <= 20
            or type(max_inputs) is not int or not 2 <= max_inputs <= 20):
        raise ParagraphInputError("invalid_paragraph_retrieval_budget")
    if not isinstance(claim, str) or not 3 <= len(claim.strip()) <= 2000:
        raise ParagraphInputError("invalid_selection_claim")
    parents = parents_from_audits(audits)
    if len({p.passage_id for p in parents}) != len(parents):
        raise ParagraphInputError("duplicate_parent_passage")
    eligible=[]
    for parent, audit in zip(parents, audits, strict=True):
        rank=getattr(audit.candidate, "rank", None)
        if type(rank) is not int or rank < 1:
            raise ParagraphInputError("invalid_paragraph_retrieval_rank")
        count=sum(external_subject_grounded(claim, p.text) for p in _paragraphs(parent).contexts)
        if 0 < count < max_inputs:
            eligible.append((rank, parent.passage_id.hex, parent, audit.candidate, count))
    eligible.sort(key=lambda row:(row[0],row[1]))
    pairs=[]
    for index,left in enumerate(eligible):
        for right in eligible[index+1:]:
            if (left[2].document_version_id != right[2].document_version_id
                    and left[4]+right[4] <= max_inputs):
                pairs.append((max(left[0],right[0]),left[0]+right[0],
                              left[0],right[0],left[1],right[1],left,right))
    if not pairs:
        return ()
    best=min(pairs,key=lambda row:row[:6])
    selected=[best[-2],best[-1]]
    identities={p[2].passage_id for p in selected}
    used=sum(p[4] for p in selected)
    for row in eligible:
        if len(selected) >= max_parents:
            break
        if row[2].passage_id not in identities and used+row[4] <= max_inputs:
            selected.append(row)
            identities.add(row[2].passage_id)
            used+=row[4]
    selected.sort(key=lambda row:(row[0],row[1]))
    # Replay the unchanged paragraph policy before returning actual stored
    # candidates. The NLI service re-audits them and re-derives their inputs.
    replay=_select(tuple(row[2] for row in selected), claim)
    if len(replay.inputs) != used or used > max_inputs:
        raise ParagraphInputError("paragraph_retrieval_selection_replay_mismatch")
    return tuple(row[3] for row in selected)


def parent_matches_candidate(parent, candidate):
    return all(getattr(parent, key) == getattr(candidate, key, None) for key in (
        "passage_id", "document_id", "document_version_id", "source_id", "publisher_name",
        "publisher_domain", "original_url", "retrieved_at", "passage_text",
        "passage_sha256", "lexical_relevance_score"))


@dataclass(frozen=True, slots=True)
class AuditedParagraphInput:
    candidate: ParagraphInput
    traceable: bool = True
    nli_evaluated: bool = False
    independently_verified: bool = False
    independent_corroboration_established: bool = False

    @property
    def fetch_observation_id(self): return self.candidate.parent.fetch_observation_id
    @property
    def fetch_observed_at(self): return self.candidate.parent.fetch_observed_at
