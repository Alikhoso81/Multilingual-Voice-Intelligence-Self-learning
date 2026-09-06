import enum
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Enum, Float, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base, TimestampMixin, UUIDMixin
from app.models.knowledge import EMBEDDING_DIM


class ClusterStatus(str, enum.Enum):
    open = "open"            # detected, not yet reviewed by an admin
    addressed = "addressed"  # admin added knowledge that answers it
    dismissed = "dismissed"  # admin decided it needs no action


class QuestionCluster(Base, UUIDMixin, TimestampMixin):
    """A group of semantically similar customer questions (Phase 8).

    `is_gap` = the knowledge base cannot answer the cluster's representative
    question above the confidence threshold — i.e. a knowledge gap for an admin
    to fill from the learning center.
    """

    __tablename__ = "question_clusters"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True
    )
    centroid: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    representative_text: Mapped[str] = mapped_column(Text, nullable=False)
    member_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    top_kb_similarity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    is_gap: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    status: Mapped[ClusterStatus] = mapped_column(
        Enum(ClusterStatus), nullable=False, default=ClusterStatus.open
    )
    resolved_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_documents.id", ondelete="SET NULL"), nullable=True
    )

    members: Mapped[list["QuestionClusterMember"]] = relationship(
        back_populates="cluster", cascade="all, delete-orphan"
    )


class QuestionClusterMember(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "question_cluster_members"

    cluster_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("question_clusters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # a message belongs to at most one cluster
    )
    similarity: Mapped[float] = mapped_column(Float, nullable=False)

    cluster: Mapped["QuestionCluster"] = relationship(back_populates="members")
