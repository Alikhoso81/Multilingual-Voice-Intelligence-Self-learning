from pydantic import BaseModel


class DashboardOverview(BaseModel):
    total_conversations: int
    analyzed_conversations: int
    conversation_status: dict[str, int]
    sentiment_breakdown: dict[str, int]
    resolution_breakdown: dict[str, int]

    total_messages: int
    customer_messages: int
    assistant_messages: int
    answered_replies: int
    deflected_replies: int
    deflection_rate: float

    intent_breakdown: dict[str, int]
    language_breakdown: dict[str, int]

    clusters_total: int
    open_gaps: int
    clusters_addressed: int

    knowledge_documents: int
    knowledge_chunks: int
