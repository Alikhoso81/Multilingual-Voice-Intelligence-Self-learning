"""
Turn an admin-authored answer into retrievable knowledge (Phase 8 learning loop).

This is the *controlled* part of "self-learning": new knowledge only becomes
retrievable when an admin approves it here — there is no automatic fine-tuning
or unsupervised ingestion.
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.knowledge import DocumentStatus, DocumentType, KnowledgeChunk, KnowledgeDocument
from app.services.rag.chunking import chunk_text
from app.services.rag.embeddings import embed_passages_batch


def curate_answer(
    db: Session,
    *,
    organization_id: uuid.UUID,
    uploaded_by: uuid.UUID,
    title: str,
    answer_text: str,
) -> KnowledgeDocument:
    """Create a `curated` KnowledgeDocument from `answer_text`, chunk + embed it,
    and return it ready. Caller commits."""
    chunks = chunk_text(answer_text)
    if not chunks:
        raise ValueError("Answer produced no chunks")
    vectors = embed_passages_batch(chunks)

    document = KnowledgeDocument(
        organization_id=organization_id,
        uploaded_by=uploaded_by,
        filename=title[:500],
        file_path="curated",
        document_type=DocumentType.curated,
        status=DocumentStatus.ready,
    )
    db.add(document)
    db.flush()
    for idx, (chunk_content, vector) in enumerate(zip(chunks, vectors)):
        db.add(
            KnowledgeChunk(
                document_id=document.id,
                organization_id=organization_id,
                chunk_index=idx,
                text=chunk_content,
                embedding=vector,
                chunk_metadata={"source": "learning_center", "title": title},
            )
        )
    return document
