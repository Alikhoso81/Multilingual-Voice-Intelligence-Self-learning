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
from app.models.conversation_message import DetectedLanguage
from app.models.learning import ClusterStatus, QuestionCluster, QuestionClusterMember
from app.services.llm.answering import (
    ANSWERED,
    LOW_CONFIDENCE,
    NO_DOCUMENTS,
    generate_grounded_answer,
)
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

    db.commit()  # persist the clustering before gap detection (which may roll back)

    _recompute_gaps(db, organization_id, touched)

    return ClusteringRun(
        messages_processed=len(messages),
        clusters_created=created,
        clusters_updated=len(touched) - created,
        open_gaps=_count_open_gaps(db, organization_id),
    )


def _recompute_gaps(db: Session, organization_id: uuid.UUID, cluster_ids: set[uuid.UUID]) -> None:
    """For each touched cluster, decide whether the KB can answer it.

    multilingual-e5 similarity alone is a weak signal (it rarely drops below
    ~0.78 even for unrelated text), so a cluster in the ambiguous band is run
    through the answer pipeline: if the representative question gets refused, the
    refusal *is* the knowledge gap. Clusters well above / below the band skip the
    LLM call. Committed per cluster so a mid-batch failure keeps earlier results.
    """
    low = settings.GAP_SIMILARITY_THRESHOLD - 0.06
    high = settings.GAP_SIMILARITY_THRESHOLD + 0.06

    for cluster_id in cluster_ids:
        cluster = db.get(QuestionCluster, cluster_id)
        if cluster is None:
            continue

        hits = retrieve_relevant_chunks(db, organization_id, cluster.representative_text, top_k=1)
        top_similarity = hits[0].similarity if hits else 0.0
        db.rollback()

        cluster = db.get(QuestionCluster, cluster_id)
        cluster.top_kb_similarity = top_similarity

        # the "mock" provider always answers, so the pipeline check is
        # uninformative there — fall back to the plain similarity rule.
        use_pipeline = settings.LLM_PROVIDER.lower() != "mock" and low <= top_similarity < high

        if cluster.status != ClusterStatus.open:
            cluster.is_gap = False
        elif not use_pipeline:
            cluster.is_gap = top_similarity < settings.GAP_SIMILARITY_THRESHOLD
        else:
            answer = generate_grounded_answer(
                db, organization_id, cluster.representative_text, DetectedLanguage.english
            )
            cluster = db.get(QuestionCluster, cluster_id)
            cluster.top_kb_similarity = top_similarity
            if answer.reason == ANSWERED:
                cluster.is_gap = False
            elif answer.reason in (LOW_CONFIDENCE, NO_DOCUMENTS):
                cluster.is_gap = True
            # provider_error -> leave is_gap unchanged (can't tell)
        db.commit()


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
