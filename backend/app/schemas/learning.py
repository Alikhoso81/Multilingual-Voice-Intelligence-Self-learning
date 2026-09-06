import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.learning import ClusterStatus


class ReclusterOut(BaseModel):
    messages_processed: int
    clusters_created: int
    clusters_updated: int
    open_gaps: int


class ClusterOut(BaseModel):
    id: uuid.UUID
    label: str | None
    representative_text: str
    member_count: int
    top_kb_similarity: float
    is_gap: bool
    status: ClusterStatus
    resolved_document_id: uuid.UUID | None
    created_at: datetime

    class Config:
        from_attributes = True


class ClusterMemberOut(BaseModel):
    message_id: uuid.UUID
    text: str
    similarity: float


class ClusterDetailOut(ClusterOut):
    members: list[ClusterMemberOut] = []


class ResolveClusterIn(BaseModel):
    title: str
    answer_text: str
