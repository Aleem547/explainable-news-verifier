"""Deterministic offline demonstration; no database, network or model loading."""

from datetime import UTC, datetime

from ml.provenance.identity import sha256_text
from ml.verification.source_context import (
    SourceObservationMethod,
    SourceProfileSignals,
    assess_context,
)


def main() -> None:
    result = assess_context(
        published_at=datetime(2020, 2, 1, tzinfo=UTC),
        retrieved_at=datetime(2026, 1, 10, tzinfo=UTC),
        assessed_at=datetime(2026, 1, 10, tzinfo=UTC),
        reference_at=datetime(2023, 1, 1, tzinfo=UTC),
        max_age_days=365,
        content_sha256=sha256_text("A licensed example article."),
        retrieval_observed=True,
        profile=SourceProfileSignals(
            method=SourceObservationMethod.PROVIDER_METADATA,
            observed_at=datetime(2026, 1, 5, tzinfo=UTC),
            publisher_name_reported="Example Publisher",
        ),
    )
    print("Phase 9D offline checks passed")
    print(f"Temporal relation: {result.temporal_relation.value}")
    print(f"Caller-defined freshness: {result.freshness_status.value}")
    print(f"Metadata flags: {list(result.metadata_flags)}")
    print(f"Warnings: {list(result.warnings)}")
    print("No requests, database writes, or claim verdicts performed")


if __name__ == "__main__":
    main()
