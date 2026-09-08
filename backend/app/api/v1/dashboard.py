"""
Dashboard aggregates (Phase 9) — one call returns everything the admin/agent
dashboard needs for the current organization. Business-impact metrics (Phase 10)
build on the same numbers.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_db, require_roles
from app.models.conversation import Conversation
from app.models.conversation_message import Message, MessageRole
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.models.learning import ClusterStatus, QuestionCluster
from app.models.message_source import MessageSource
from app.models.user import User, UserRole
from app.schemas.dashboard import DashboardOverview

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_STAFF = require_roles(UserRole.admin, UserRole.agent)


def _counts(db: Session, column, base_filter) -> dict[str, int]:
    rows = db.execute(
        select(column, func.count()).where(base_filter).group_by(column)
    ).all()
    return {str(getattr(k, "value", k)): v for k, v in rows if k is not None}


@router.get("/overview", response_model=DashboardOverview)
def overview(
    db: Session = Depends(get_db),
    current_user: User = Depends(_STAFF),
) -> DashboardOverview:
    org_id = current_user.organization_id
    conv_org = Conversation.organization_id == org_id
    msg_in_org = Message.conversation_id.in_(
        select(Conversation.id).where(conv_org)
    )

    total_conversations = db.execute(
        select(func.count()).select_from(Conversation).where(conv_org)
    ).scalar() or 0
    analyzed = db.execute(
        select(func.count()).select_from(Conversation).where(
            conv_org, Conversation.analyzed_at.is_not(None)
        )
    ).scalar() or 0

    total_messages = db.execute(
        select(func.count()).select_from(Message).where(msg_in_org)
    ).scalar() or 0
    customer_messages = db.execute(
        select(func.count()).select_from(Message).where(
            msg_in_org, Message.role == MessageRole.customer
        )
    ).scalar() or 0
    assistant_messages = total_messages - customer_messages

    # answered vs deflected: an assistant reply that cited >=1 chunk was answered.
    answered = db.execute(
        select(func.count(func.distinct(MessageSource.message_id)))
        .select_from(MessageSource)
        .join(Message, Message.id == MessageSource.message_id)
        .where(msg_in_org)
    ).scalar() or 0
    deflected = max(0, assistant_messages - answered)

    clusters_total = db.execute(
        select(func.count()).select_from(QuestionCluster).where(
            QuestionCluster.organization_id == org_id
        )
    ).scalar() or 0
    open_gaps = db.execute(
        select(func.count()).select_from(QuestionCluster).where(
            QuestionCluster.organization_id == org_id, QuestionCluster.is_gap.is_(True)
        )
    ).scalar() or 0

    documents = db.execute(
        select(func.count()).select_from(KnowledgeDocument).where(
            KnowledgeDocument.organization_id == org_id
        )
    ).scalar() or 0
    chunks = db.execute(
        select(func.count()).select_from(KnowledgeChunk).where(
            KnowledgeChunk.organization_id == org_id
        )
    ).scalar() or 0

    return DashboardOverview(
        total_conversations=total_conversations,
        analyzed_conversations=analyzed,
        conversation_status=_counts(db, Conversation.status, conv_org),
        sentiment_breakdown=_counts(db, Conversation.sentiment, conv_org),
        resolution_breakdown=_counts(db, Conversation.resolution, conv_org),
        total_messages=total_messages,
        customer_messages=customer_messages,
        assistant_messages=assistant_messages,
        answered_replies=answered,
        deflected_replies=deflected,
        deflection_rate=round(deflected / assistant_messages, 3) if assistant_messages else 0.0,
        intent_breakdown=_counts(
            db, Message.intent, msg_in_org & (Message.role == MessageRole.customer)
        ),
        language_breakdown=_counts(
            db, Message.language, msg_in_org & (Message.role == MessageRole.customer)
        ),
        clusters_total=clusters_total,
        open_gaps=open_gaps,
        clusters_addressed=db.execute(
            select(func.count()).select_from(QuestionCluster).where(
                QuestionCluster.organization_id == org_id,
                QuestionCluster.status == ClusterStatus.addressed,
            )
        ).scalar() or 0,
        knowledge_documents=documents,
        knowledge_chunks=chunks,
    )
