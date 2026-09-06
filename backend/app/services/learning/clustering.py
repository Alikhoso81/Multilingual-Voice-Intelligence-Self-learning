"""
Question clustering + knowledge-gap detection (Phase 8).

Greedy online clustering over customer-question embeddings: each unclustered
customer message joins the nearest existing cluster (cosine >=
CLUSTER_SIMILARITY_THRESHOLD) or seeds a new one. Centroids update incrementally
(exact running mean), so old members are never re-embedded. After a run, each
touched cluster's knowledge-gap flag is recomputed by retrieving its
representative question against the knowledge base.

O(new_messages x clusters) and single-transaction — fine at FYP scale. For
production volume this belongs in a Celery job with batched embedding.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.conversation import Conversation
from app.models.conversation_message import Message, MessageRole
from app.models.learning import ClusterStatus, QuestionCluster, QuestionClusterMember
from app.services.rag.embeddings import embed_query
from app.services.rag.retrieval import retrieve_relevant_chunks


@dataclass
class ClusteringRun:
    messages_processed: int
    clusters_created: int
    clusters_updated: int
    open_gaps: int


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def _blend(centroid: list[float], count: int, vec: list[float]) -> list[float]:
    """Exact running mean: fold one new vector into a centroid of `count` vectors."""
    return [(c * count + v) / (count + 1) for c, v in zip(centroid, vec)]


def recluster_organization(
    db: Session, organization_id: uuid.UUID, limit: int = 300
) -> ClusteringRun:
    clustered = select(QuestionClusterMember.message_id)
    messages = list(
        db.execute(
            select(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Conversation.organization_id == organization_id,
                Message.role == MessageRole.customer,
                Message.id.not_in(clustered),
            )
            .order_by(Message.created_at)
            .limit(limit)
        ).scalars()
    )

    clusters = list(
        db.execute(
            select(QuestionCluster).where(QuestionCluster.organization_id == organization_id)
        ).scalars()
    )

    created = 0
    touched: set[uuid.UUID] = set()
    threshold = settings.CLUSTER_SIMILARITY_THRESHOLD

    for msg in messages:
        text = (msg.normalized_text or msg.raw_text or "").strip()
        if not text:
            continue
        vec = embed_query(text)

        best, best_sim = None, 0.0
        for cluster in clusters:
            sim = _cosine(vec, list(cluster.centroid))
            if sim > best_sim:
                best, best_sim = cluster, sim

        if best is not None and best_sim >= threshold:
            best.centroid = _blend(list(best.centroid), best.member_count, vec)
            best.member_count += 1
            db.add(QuestionClusterMember(cluster_id=best.id, message_id=msg.id, similarity=best_sim))
            touched.add(best.id)
        else:
            cluster = QuestionCluster(
                organization_id=organization_id,
                centroid=vec,
                representative_text=text,
                member_count=1,
                status=ClusterStatus.open,
            )
            db.add(cluster)
            db.flush()
            db.add(QuestionClusterMember(cluster_id=cluster.id, message_id=msg.id, similarity=1.0))
            clusters.append(cluster)
            touched.add(cluster.id)
            created += 1

    # recompute the knowledge-gap flag for every cluster we touched
    for cluster in clusters:
        if cluster.id not in touched:
            continue
        hits = retrieve_relevant_chunks(db, organization_id, cluster.representative_text, top_k=1)
        cluster.top_kb_similarity = hits[0].similarity if hits else 0.0
        cluster.is_gap = (
            cluster.status == ClusterStatus.open
            and cluster.top_kb_similarity < settings.RAG_CONFIDENCE_THRESHOLD
        )

    db.commit()
    return ClusteringRun(
        messages_processed=len(messages),
        clusters_created=created,
        clusters_updated=len(touched) - created,
        open_gaps=_count_open_gaps(db, organization_id),
    )


def _count_open_gaps(db: Session, organization_id: uuid.UUID) -> int:
    return (
        db.execute(
            select(func.count())
            .select_from(QuestionCluster)
            .where(
                QuestionCluster.organization_id == organization_id,
                QuestionCluster.is_gap.is_(True),
            )
        ).scalar()
        or 0
    )
