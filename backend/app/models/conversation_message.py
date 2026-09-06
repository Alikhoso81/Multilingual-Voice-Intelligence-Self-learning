import enum
import uuid

from sqlalchemy import Enum, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base, TimestampMixin, UUIDMixin


class MessageRole(str, enum.Enum):
    customer = "customer"
    system = "system"
    agent = "agent"


class DetectedLanguage(str, enum.Enum):
    english = "en"
    urdu = "ur"
    roman_urdu = "roman-ur"
    mixed = "mixed"
    unknown = "unknown"


class MessageIntent(str, enum.Enum):
    """Coarse support intents (Phase 5). Industry-agnostic on purpose — telecom,
    banking, e-commerce etc. all map onto these."""

    billing = "billing"                       # charges, invoices, payments, refunds
    technical_support = "technical_support"    # something not working
    account_management = "account_management"  # sign-up, cancel, update details, SIM/number
    complaint = "complaint"                    # dissatisfaction, escalation
    sales_inquiry = "sales_inquiry"            # pricing, packages, upgrades, availability
    general_inquiry = "general_inquiry"        # hours, contact info, how-to
    other = "other"                            # valid message, none of the above
    unknown = "unknown"                        # classification unavailable / failed


class Message(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False
    )
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole), default=MessageRole.customer)

    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True, doc="Original transcript/typed text")
    normalized_text: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="Canonicalized text used for intent/RAG/clustering"
    )
    language: Mapped[DetectedLanguage] = mapped_column(
        Enum(DetectedLanguage), default=DetectedLanguage.unknown
    )
    asr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Phase 5 — NLU on customer messages (null on system/agent messages)
    intent: Mapped[MessageIntent | None] = mapped_column(Enum(MessageIntent), nullable=True)
    intent_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    entities: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
    voice_recording: Mapped["VoiceRecording | None"] = relationship(
        back_populates="message", uselist=False
    )
    sources: Mapped[list["MessageSource"]] = relationship(
        back_populates="message", cascade="all, delete-orphan", order_by="MessageSource.rank"
    )


class VoiceRecording(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "voice_recordings"

    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id"), nullable=False
    )
    audio_path: Mapped[str] = mapped_column(String(500), nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    message: Mapped["Message"] = relationship(back_populates="voice_recording")
