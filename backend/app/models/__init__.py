# Import all models here so Alembic autogenerate can discover them via Base.metadata
from app.models.organization import Organization  # noqa
from app.models.user import User, UserRole  # noqa
from app.models.customer import Customer  # noqa
from app.models.conversation import (  # noqa
    Conversation,
    ConversationStatus,
    ConversationChannel,
    ConversationSentiment,
    ConversationResolution,
)
from app.models.conversation_message import Message, MessageRole, DetectedLanguage, MessageIntent, VoiceRecording  # noqa
from app.models.knowledge import KnowledgeDocument, KnowledgeChunk, DocumentType, DocumentStatus  # noqa
from app.models.message_source import MessageSource  # noqa
from app.models.learning import QuestionCluster, QuestionClusterMember, ClusterStatus  # noqa
