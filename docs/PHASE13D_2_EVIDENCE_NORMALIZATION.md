# Phase 13D.2 — External evidence normalization and provisional deduplication

## Scope

Pure, offline processing of the `ExternalPassageCandidate` objects returned by
Phase 13D.1. No network calls, database changes, cloud services, new libraries,
model inference, or publisher trust decisions.

### Components

- `apps/api/services/external_evidence_normalization.py`
- `tests/unit/test_phase13d2_evidence_normalization.py`

`normalize_and_group_external_evidence(candidates)` returns a frozen
`EvidenceNormalizationReport` containing groups of evidence. **Every original
candidate, document ID, publisher, URL, timestamp, score and source ID remains
accessible under `group.members[].candidate`.** The candidate's original article
text is never modified.

### Normalization

1. Unicode NFKC normalization for display/fingerprints.
2. Removal of hidden Unicode format characters.
3. Whitespace collapse and stable SHA-256 fingerprints (case-insensitive).
4. Independent integrity checks against the original candidate passage hash.

### Duplicate handling

- **Exact** = identical normalized SHA-256. This only describes passage text;
  it does NOT establish that publishers are independent.
- **Near** = tentative four-token shingle Jaccard >= 0.92 for passages of
  at least 24 tokens, and only when number and negation signatures match.
  A near match means *possible duplication*, **not** that the two passages
  have identical meaning. Its input is retained for future NLI evaluation.
- A group representative is the highest *retrieval relevance* candidate,
  not the most trustworthy or factually correct publisher.
- Prevent similarity chaining: each near match is compared against the
  group's original representative, not arbitrarily against any member.
- Each candidate has a unique passage UUID. Duplicate IDs cause failure.

### Safety properties

- Refuse invalid or tampered passage hashes, unbounded inputs, nonpositive,
  infinite or NaN relevance scores, naive timestamps and insecure HTTP URLs.
- Refuse already assessed candidates to ensure group output cannot silently
  inherit NLI/independence/truth flags.
- Set `independently_verified` and `independent_corroboration_established`
  to `False` throughout; no corroboration claims are made here.

### Test instructions — Windows PowerShell

```powershell
cd C:\Projects\explainable-news-verifier
& .\.venv\Scripts\python.exe -m unittest discover -s tests/unit -p "test_phase13d2_evidence_normalization.py" -v
& .\.venv\Scripts\python.exe -m unittest discover -s tests/unit -p "test_phase13d1_external_retrieval.py" -v
git diff --check
git status -sb
```

Expected: **21 Phase 13D.2 unit tests**, plus **14 Phase 13D.1 regression tests**.

### Not done in this phase

This is an offline grouping aid. No publisher independence or syndication
investigation has been done. Detection of near duplicates remains heuristic.
Do not suppress potentially contradictory evidence or declare sources
corroborating a claim based solely on these groups. Phase 13D.3 adds
provenance context; 13D.4 adds independent-source analysis; 13D.5 adds NLI.
