import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user, get_db
from app.models.conversation import Conversation
from app.models.conversation_message import Message, MessageRole, VoiceRecording
from app.models.message_source import MessageSource
from app.models.user import User
from app.schemas.conversation import (
    AssistantMessageOut,
    ConversationCreate,
    ConversationOut,
    MessageExchangeOut,
    MessageOut,
    MessageSourceOut,
    TextMessageCreate,
)
from app.services.llm.answering import GroundedAnswer, generate_grounded_answer
from app.services.speech.language_utils import detect_language, normalize_text
from app.services.speech.whisper_service import transcribe_audio

router = APIRouter(prefix="/conversations", tags=["conversations"])

AUDIO_STORAGE_DIR = settings.audio_storage_dir
AUDIO_STORAGE_DIR.mkdir(parents=True, exist_ok=True)


@router.post("", response_model=ConversationOut, status_code=201)
def create_conversation(
    payload: ConversationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Conversation:
    conversation = Conversation(
        organization_id=current_user.organization_id,
        customer_id=payload.customer_id,
        channel=payload.channel,
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


@router.get("/{conversation_id}", response_model=ConversationOut)
def get_conversation(
    conversation_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Conversation:
    return _get_owned_conversation(db, conversation_id, current_user)


@router.post(
    "/{conversation_id}/messages/text",
    response_model=MessageExchangeOut,
    status_code=201,
)
def send_text_message(
    conversation_id: uuid.UUID,
    payload: TextMessageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MessageExchangeOut:
    """
    Store a typed customer message, then (Phase 4) retrieve relevant knowledge and
    generate a grounded assistant reply — or a human-handoff message if retrieval
    confidence is below the threshold. Returns both messages.
    """
    conversation = _get_owned_conversation(db, conversation_id, current_user)

    language = detect_language(payload.text)
    customer_message = Message(
        conversation_id=conversation.id,
        role=MessageRole.customer,
        raw_text=payload.text,
        normalized_text=normalize_text(payload.text, language),
        language=language,
        asr_confidence=None,  # not applicable to typed text
    )
    db.add(customer_message)
    db.commit()
    db.refresh(customer_message)

    assistant_message, answer = _generate_assistant_reply(db, conversation, customer_message)
    return _build_exchange(customer_message, assistant_message, answer)


@router.post(
    "/{conversation_id}/messages/voice",
    response_model=MessageExchangeOut,
    status_code=201,
)
async def send_voice_message(
    conversation_id: uuid.UUID,
    audio: UploadFile,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MessageExchangeOut:
    """
    Accept an audio file, transcribe it with Faster-Whisper, detect language and
    normalize, store the customer message + audio reference, then generate a
    grounded assistant reply (same pipeline as the text endpoint).
    """
    conversation = _get_owned_conversation(db, conversation_id, current_user)

    if not audio.filename:
        raise HTTPException(status_code=400, detail="No audio file provided")

    suffix = Path(audio.filename).suffix or ".wav"
    saved_path = AUDIO_STORAGE_DIR / f"{uuid.uuid4()}{suffix}"
    with saved_path.open("wb") as f:
        shutil.copyfileobj(audio.file, f)

    try:
        result = transcribe_audio(str(saved_path))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not transcribe audio: {exc}")

    if not result.text:
        raise HTTPException(
            status_code=422,
            detail="Transcription returned empty text — audio may be silent, "
            "unsupported format, or too noisy.",
        )

    language = detect_language(result.text, whisper_language_hint=result.whisper_language)
    customer_message = Message(
        conversation_id=conversation.id,
        role=MessageRole.customer,
        raw_text=result.text,
        normalized_text=normalize_text(result.text, language),
        language=language,
        asr_confidence=result.avg_logprob_confidence,
    )
    db.add(customer_message)
    db.flush()  # need message.id for the voice_recording row
    db.add(
        VoiceRecording(
            message_id=customer_message.id,
            audio_path=str(saved_path),
            duration_seconds=result.duration_seconds,
        )
    )
    db.commit()
    db.refresh(customer_message)

    assistant_message, answer = _generate_assistant_reply(db, conversation, customer_message)
    return _build_exchange(customer_message, assistant_message, answer)


def _generate_assistant_reply(
    db: Session, conversation: Conversation, customer_message: Message
) -> tuple[Message, GroundedAnswer]:
    query_text = customer_message.normalized_text or customer_message.raw_text or ""
    answer = generate_grounded_answer(
        db, conversation.organization_id, query_text, customer_message.language
    )

    assistant_message = Message(
        conversation_id=conversation.id,
        role=MessageRole.system,
        raw_text=answer.text,
        normalized_text=None,
        language=answer.language,
        asr_confidence=None,
    )
    db.add(assistant_message)
    db.flush()
    for rank, src in enumerate(answer.sources):
        db.add(
            MessageSource(
                message_id=assistant_message.id,
                chunk_id=src.chunk_id,
                similarity=src.similarity,
                rank=rank,
            )
        )
    db.commit()
    db.refresh(assistant_message)
    return assistant_message, answer


def _build_exchange(
    customer_message: Message, assistant_message: Message, answer: GroundedAnswer
) -> MessageExchangeOut:
    return MessageExchangeOut(
        customer_message=MessageOut.model_validate(customer_message),
        assistant_message=AssistantMessageOut(
            id=assistant_message.id,
            role=assistant_message.role,
            raw_text=assistant_message.raw_text,
            language=assistant_message.language,
            created_at=assistant_message.created_at,
            answered=answer.answered,
            reason=answer.reason,
            provider=answer.provider,
            model=answer.model,
            top_similarity=answer.top_similarity,
            sources=[
                MessageSourceOut(
                    chunk_id=s.chunk_id, document_id=s.document_id, similarity=s.similarity
                )
                for s in answer.sources
            ],
        ),
    )


def _get_owned_conversation(
    db: Session, conversation_id: uuid.UUID, current_user: User
) -> Conversation:
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.organization_id == current_user.organization_id,
        )
        .first()
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation
