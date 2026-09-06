import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.knowledge import DocumentStatus, DocumentType


class DocumentOut(BaseModel):
    id: uuid.UUID
    filename: str
    document_type: DocumentType
    status: DocumentStatus
    error_message: str | None
    created_at: datetime
    chunk_count: int = 0

    class Config:
        from_attributes = True


class RetrievalQuery(BaseModel):
    query: str
    top_k: int = 5


class RetrievedChunkOut(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    text: str
    similarity: float
