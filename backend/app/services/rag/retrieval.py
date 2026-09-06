"""
Retrieval over the knowledge base using pgvector cosine similarity.

Since embeddings are normalized (see embeddings.py), cosine distance and dot
product rank identically — we use pgvector's cosine_distance operator (`<=>`)
via the ORM helper, which is the most explicit/readable option.
"""
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.knowledge import KnowledgeChunk
from app.services.rag.embeddings import embed_query


@dataclass
class RetrievedChunk:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    text: str
    similarity: float  # 0..1, higher = more relevant


def retrieve_relevant_chunks(
    db: Session,
    organization_id: uuid.UUID,
    query_text: str,
    top_k: int = 5,
) -> list[RetrievedChunk]:
    query_vector = embed_query(query_text)

    # pgvector's <=> is cosine distance: 0 (identical) .. 2 (opposite).
    # similarity = 1 - distance = plain cosine similarity in [-1, 1], clamped
    # to [0, 1]. We report raw cosine (not a remapped score) because that's the
    # number the confidence threshold is tuned against and the one every
    # embedding-model doc quotes. Note multilingual-e5 runs "hot" — unrelated
    # text still lands around 0.72-0.78, a real topical match around 0.80-0.88.
    distance_expr = KnowledgeChunk.embedding.cosine_distance(query_vector)

    stmt = (
        select(KnowledgeChunk, distance_expr.label("distance"))
        .where(KnowledgeChunk.organization_id == organization_id)
        .order_by(distance_expr)
        .limit(top_k)
    )

    results = db.execute(stmt).all()

    return [
        RetrievedChunk(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            text=chunk.text,
            similarity=max(0.0, min(1.0, 1.0 - distance)),
        )
        for chunk, distance in results
    ]
