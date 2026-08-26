import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.conversation import ConversationChannel, ConversationStatus
from app.models.conversation_message import DetectedLanguage, MessageRole


class ConversationCreate(BaseModel):
    customer_id: uuid.UUID | None = None
    channel: ConversationChannel = ConversationChannel.text


class MessageOut(BaseModel):
    id: uuid.UUID
    role: MessageRole
    raw_text: str | None
    normalized_text: str | None
    language: DetectedLanguage
    asr_confidence: float | None
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationOut(BaseModel):
    id: uuid.UUID
    channel: ConversationChannel
    status: ConversationStatus
    summary: str | None
    messages: list[MessageOut] = []

    class Config:
        from_attributes = True


class TextMessageCreate(BaseModel):
    text: str
