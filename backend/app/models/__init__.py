# Import all models here so Alembic autogenerate can discover them via Base.metadata
from app.models.organization import Organization  # noqa
from app.models.user import User, UserRole  # noqa
from app.models.customer import Customer  # noqa
from app.models.conversation import Conversation, ConversationStatus, ConversationChannel  # noqa
from app.models.conversation_message import Message, MessageRole, DetectedLanguage, VoiceRecording  # noqa
