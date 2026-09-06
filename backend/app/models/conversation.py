import enum
import uuid

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base, TimestampMixin, UUIDMixin


class ConversationStatus(str, enum.Enum):
    open = "open"
    resolved = "resolved"
    escalated = "escalated"


class ConversationChannel(str, enum.Enum):
    voice = "voice"
    text = "text"


class ConversationSentiment(str, enum.Enum):
    positive = "positive"
    neutral = "neutral"
    negative = "negative"
    frustrated = "frustrated"
    unknown = "unknown"


class ConversationResolution(str, enum.Enum):
    resolved = "resolved"              # customer's need was met
    unresolved = "unresolved"          # not answered / customer still stuck
    needs_follow_up = "needs_follow_up"  # partial; a human should follow up
    escalated = "escalated"            # handed to a human representative
    unknown = "unknown"


class Conversation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "conversations"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=True
    )
    channel: Mapped[ConversationChannel] = mapped_column(
        Enum(ConversationChannel), default=ConversationChannel.text
    )
    status: Mapped[ConversationStatus] = mapped_column(
        Enum(ConversationStatus), default=ConversationStatus.open
    )

    # Phase 7 — analytics over the transcript
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    sentiment: Mapped[ConversationSentiment | None] = mapped_column(
        Enum(ConversationSentiment), nullable=True
    )
    resolution: Mapped[ConversationResolution | None] = mapped_column(
        Enum(ConversationResolution), nullable=True
    )
    follow_up: Mapped[str | None] = mapped_column(Text, nullable=True)
    analyzed_at: Mapped["DateTime | None"] = mapped_column(DateTime(timezone=True), nullable=True)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", order_by="Message.created_at"
    )
