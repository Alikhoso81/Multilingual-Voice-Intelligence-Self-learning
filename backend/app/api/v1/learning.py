"""
Learning center (Phase 8): review clustered customer questions, see which ones
the knowledge base can't answer (gaps), and approve new knowledge to close them.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_db, require_roles
from app.models.conversation_message import Message
from app.models.learning import ClusterStatus, QuestionCluster, QuestionClusterMember
from app.models.user import User, UserRole
from app.schemas.learning import (
    ClusterDetailOut,
    ClusterMemberOut,
    ClusterOut,
    ReclusterOut,
    ResolveClusterIn,
)
from app.services.learning.clustering import recluster_organization
from app.services.learning.curate import curate_answer

router = APIRouter(prefix="/learning", tags=["learning"])

_STAFF = require_roles(UserRole.admin, UserRole.agent)
_ADMIN = require_roles(UserRole.admin)


@router.post("/recluster", response_model=ReclusterOut)
def recluster(
    db: Session = Depends(get_db),
    current_user: User = Depends(_STAFF),
) -> ReclusterOut:
    run = recluster_organization(db, current_user.organization_id)
    return ReclusterOut(**run.__dict__)


@router.get("/clusters", response_model=list[ClusterOut])
def list_clusters(
    db: Session = Depends(get_db),
    current_user: User = Depends(_STAFF),
    status: ClusterStatus | None = None,
    gap: bool | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[QuestionCluster]:
    stmt = select(QuestionCluster).where(
        QuestionCluster.organization_id == current_user.organization_id
    )
    if status is not None:
        stmt = stmt.where(QuestionCluster.status == status)
    if gap is not None:
        stmt = stmt.where(QuestionCluster.is_gap.is_(gap))
    stmt = stmt.order_by(QuestionCluster.member_count.desc()).limit(limit)
    return list(db.execute(stmt).scalars())


@router.get("/gaps", response_model=list[ClusterOut])
def list_gaps(
    db: Session = Depends(get_db),
    current_user: User = Depends(_STAFF),
) -> list[QuestionCluster]:
    return list(
        db.execute(
            select(QuestionCluster)
            .where(
                QuestionCluster.organization_id == current_user.organization_id,
                QuestionCluster.is_gap.is_(True),
            )
            .order_by(QuestionCluster.member_count.desc())
        ).scalars()
    )


@router.get("/clusters/{cluster_id}", response_model=ClusterDetailOut)
def get_cluster(
    cluster_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(_STAFF),
) -> ClusterDetailOut:
    cluster = _owned_cluster(db, cluster_id, current_user)
    rows = db.execute(
        select(QuestionClusterMember.message_id, Message.raw_text, Message.normalized_text,
               QuestionClusterMember.similarity)
        .join(Message, Message.id == QuestionClusterMember.message_id)
        .where(QuestionClusterMember.cluster_id == cluster.id)
        .order_by(QuestionClusterMember.similarity.desc())
    ).all()
    return ClusterDetailOut(
        **ClusterOut.model_validate(cluster).model_dump(),
        members=[
            ClusterMemberOut(message_id=mid, text=(nt or rt or ""), similarity=sim)
            for mid, rt, nt, sim in rows
        ],
    )


@router.post("/clusters/{cluster_id}/resolve", response_model=ClusterDetailOut)
def resolve_cluster(
    cluster_id: uuid.UUID,
    payload: ResolveClusterIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(_ADMIN),
) -> ClusterDetailOut:
    """Admin approves new knowledge for this cluster. The answer is chunked +
    embedded and becomes retrievable immediately."""
    cluster = _owned_cluster(db, cluster_id, current_user)
    if not payload.answer_text.strip():
        raise HTTPException(status_code=400, detail="answer_text is required")

    org_id = cluster.organization_id
    db.rollback()  # release the connection during embedding

    document = curate_answer(
        db,
        organization_id=org_id,
        uploaded_by=current_user.id,
        title=payload.title or "Curated answer",
        answer_text=payload.answer_text,
    )
    db.flush()

    cluster = _owned_cluster(db, cluster_id, current_user)
    cluster.status = ClusterStatus.addressed
    cluster.is_gap = False
    cluster.resolved_document_id = document.id
    db.commit()
    return get_cluster(cluster_id, db, current_user)


@router.post("/clusters/{cluster_id}/dismiss", response_model=ClusterOut)
def dismiss_cluster(
    cluster_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(_ADMIN),
) -> QuestionCluster:
    cluster = _owned_cluster(db, cluster_id, current_user)
    cluster.status = ClusterStatus.dismissed
    cluster.is_gap = False
    db.commit()
    db.refresh(cluster)
    return cluster


def _owned_cluster(db: Session, cluster_id: uuid.UUID, current_user: User) -> QuestionCluster:
    cluster = db.get(QuestionCluster, cluster_id)
    if cluster is None or cluster.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Cluster not found")
    return cluster
