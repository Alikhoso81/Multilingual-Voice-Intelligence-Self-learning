import enum
import uuid

from sqlalchemy import Enum, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
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

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
    voice_recording: Mapped["VoiceRecording | None"] = relationship(
        back_populates="message", uselist=False
    )


class VoiceRecording(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "voice_recordings"

    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id"), nullable=False
    )
    audio_path: Mapped[str] = mapped_column(String(500), nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    message: Mapped["Message"] = relationship(back_populates="voice_recording")
