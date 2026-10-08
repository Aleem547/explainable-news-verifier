"""Local operator-only readout of recent captured passage IDs (no content output)."""

import asyncio

from sqlalchemy import select

from apps.api.db.models.document import Document
from apps.api.db.models.document_passage import DocumentPassage
from apps.api.db.models.document_version import DocumentVersion
from apps.api.db.session import AsyncSessionLocal


async def main() -> None:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(DocumentPassage.id, DocumentVersion.id, Document.url)
                .join(DocumentVersion, DocumentPassage.document_version_id == DocumentVersion.id)
                .join(Document, DocumentVersion.document_id == Document.id)
                .order_by(DocumentVersion.retrieved_at.desc(), DocumentPassage.ordinal)
                .limit(20)
            )
        ).all()
    print("Captured, passage-indexed snapshots (IDs only; no text printed):")
    for passage_id, version_id, url in rows:
        print(f"passage_id={passage_id} version_id={version_id} url={url}")
    if not rows:
        print("No authorized article snapshots are stored yet.")


if __name__ == "__main__":
    asyncio.run(main())
