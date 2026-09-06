import uuid

from sqlalchemy import Float, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base, TimestampMixin, UUIDMixin


class MessageSource(Base, UUIDMixin, TimestampMixin):
    """Audit trail for a generated answer: which knowledge chunk grounded an
    assistant message, and how strongly it matched. One row per (message, chunk).

    Deleting the message removes its sources (CASCADE). Deleting the underlying
    document/chunk also removes these rows for now — Phase 8 can denormalize a
    document reference here if historical grounding needs to survive cleanup.
    """

    __tablename__ = "message_sources"

    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_chunks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    similarity: Mapped[float] = mapped_column(Float, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, doc="0 = best match")

    message: Mapped["Message"] = relationship(back_populates="sources")
