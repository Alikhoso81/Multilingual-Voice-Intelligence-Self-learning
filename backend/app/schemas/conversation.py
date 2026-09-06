import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.conversation import ConversationChannel, ConversationStatus
from app.models.conversation_message import DetectedLanguage, MessageIntent, MessageRole


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
    intent: MessageIntent | None
    intent_confidence: float | None
    entities: dict = {}
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


class MessageSourceOut(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    similarity: float


class AssistantMessageOut(BaseModel):
    id: uuid.UUID
    role: MessageRole
    raw_text: str | None
    language: DetectedLanguage
    created_at: datetime
    answered: bool
    reason: str
    provider: str
    model: str | None
    top_similarity: float
    sources: list[MessageSourceOut] = []


class MessageExchangeOut(BaseModel):
    """A customer message and the assistant reply it triggered."""

    customer_message: MessageOut
    assistant_message: AssistantMessageOut
