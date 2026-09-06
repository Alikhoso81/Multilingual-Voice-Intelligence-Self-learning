import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
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
from app.services.nlu.intent import IntentResult, classify_message
from app.services.speech.language_utils import detect_language, normalize_text
from app.services.speech.whisper_service import transcribe_audio
from app.services.tts.synthesis import synthesize_reply

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
) -> ConversationOut:
    conversation = _get_owned_conversation(db, conversation_id, current_user)
    messages = []
    for m in conversation.messages:
        out = MessageOut.model_validate(m)
        if m.voice_recording is not None:
            out.audio_url = _audio_url(conversation.id, m.id)
        messages.append(out)
    return ConversationOut(
        id=conversation.id,
        channel=conversation.channel,
        status=conversation.status,
        summary=conversation.summary,
        messages=messages,
    )


@router.get("/{conversation_id}/messages/{message_id}/audio")
def get_message_audio(
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    """Return the WAV for a message. Customer voice messages return the uploaded
    file; assistant replies are synthesized on first request and cached."""
    conversation = _get_owned_conversation(db, conversation_id, current_user)
    message = (
        db.query(Message)
        .filter(Message.id == message_id, Message.conversation_id == conversation.id)
        .first()
    )
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")

    if message.voice_recording is not None and Path(message.voice_recording.audio_path).exists():
        return FileResponse(message.voice_recording.audio_path, media_type="audio/wav")

    if message.role != MessageRole.system or not (message.raw_text or "").strip():
        raise HTTPException(status_code=404, detail="No audio available for this message")

    synthesized = synthesize_reply(message.raw_text, message.language)
    if synthesized is None:
        raise HTTPException(status_code=503, detail="Speech synthesis is unavailable")
    path, duration = synthesized
    db.add(
        VoiceRecording(message_id=message.id, audio_path=str(path), duration_seconds=duration)
    )
    db.commit()
    return FileResponse(str(path), media_type="audio/wav")


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
    Store a typed customer message (with intent + entities), then generate a
    grounded assistant reply — or a human-handoff message if retrieval
    confidence is below the threshold. Returns both messages.
    """
    conv_id, org_id = _owned_conversation_ids(db, conversation_id, current_user)

    language = detect_language(payload.text)
    normalized = normalize_text(payload.text, language)
    query_text = normalized or payload.text

    # Both LLM calls happen before the write transaction so no DB connection is
    # pinned during them.
    nlu = classify_message(query_text, language)
    answer = generate_grounded_answer(db, org_id, query_text, language)

    customer_message = _new_customer_message(
        conv_id, raw_text=payload.text, normalized=normalized, language=language, nlu=nlu
    )
    return _persist_exchange(db, conv_id, customer_message, answer)  # text in -> text out


@router.post(
    "/{conversation_id}/messages/text/spoken",
    response_model=MessageExchangeOut,
    status_code=201,
)
def send_text_message_spoken(
    conversation_id: uuid.UUID,
    payload: TextMessageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MessageExchangeOut:
    """Same as /messages/text but also synthesizes the assistant reply to speech."""
    conv_id, org_id = _owned_conversation_ids(db, conversation_id, current_user)

    language = detect_language(payload.text)
    normalized = normalize_text(payload.text, language)
    query_text = normalized or payload.text

    nlu = classify_message(query_text, language)
    answer = generate_grounded_answer(db, org_id, query_text, language)
    tts = synthesize_reply(answer.text, answer.language)

    customer_message = _new_customer_message(
        conv_id, raw_text=payload.text, normalized=normalized, language=language, nlu=nlu
    )
    return _persist_exchange(db, conv_id, customer_message, answer, tts=tts)


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
    Transcribe an audio file with Faster-Whisper, detect language, classify
    intent + entities, store the customer message + audio reference, then
    generate a grounded assistant reply (same pipeline as the text endpoint).
    """
    conv_id, org_id = _owned_conversation_ids(db, conversation_id, current_user)

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
    normalized = normalize_text(result.text, language)
    query_text = normalized or result.text

    nlu = classify_message(query_text, language)
    answer = generate_grounded_answer(db, org_id, query_text, language)
    # voice in -> voice out (unless disabled)
    tts = (
        synthesize_reply(answer.text, answer.language)
        if settings.TTS_AUTOSPEAK_VOICE_REPLIES
        else None
    )

    customer_message = _new_customer_message(
        conv_id,
        raw_text=result.text,
        normalized=normalized,
        language=language,
        nlu=nlu,
        asr_confidence=result.avg_logprob_confidence,
    )
    db.add(customer_message)
    db.flush()
    db.add(
        VoiceRecording(
            message_id=customer_message.id,
            audio_path=str(saved_path),
            duration_seconds=result.duration_seconds,
        )
    )
    return _persist_exchange(db, conv_id, customer_message, answer, tts=tts, already_added=True)


def _new_customer_message(
    conversation_id: uuid.UUID,
    *,
    raw_text: str,
    normalized: str,
    language,
    nlu: IntentResult,
    asr_confidence: float | None = None,
) -> Message:
    return Message(
        conversation_id=conversation_id,
        role=MessageRole.customer,
        raw_text=raw_text,
        normalized_text=normalized,
        language=language,
        asr_confidence=asr_confidence,
        intent=nlu.intent,
        intent_confidence=nlu.confidence,
        entities=nlu.entities,
    )


def _persist_exchange(
    db: Session,
    conversation_id: uuid.UUID,
    customer_message: Message,
    answer: GroundedAnswer,
    *,
    tts: tuple[Path, float] | None = None,
    already_added: bool = False,
) -> MessageExchangeOut:
    if not already_added:
        db.add(customer_message)
        db.flush()

    assistant_message = Message(
        conversation_id=conversation_id,
        role=MessageRole.system,
        raw_text=answer.text,
        normalized_text=None,
        language=answer.language,
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
    if tts is not None:
        audio_path, audio_duration = tts
        db.add(
            VoiceRecording(
                message_id=assistant_message.id,
                audio_path=str(audio_path),
                duration_seconds=audio_duration,
            )
        )
    db.commit()
    db.refresh(customer_message)
    db.refresh(assistant_message)

    customer_out = MessageOut.model_validate(customer_message)
    if customer_message.voice_recording is not None:
        customer_out.audio_url = _audio_url(conversation_id, customer_message.id)

    return MessageExchangeOut(
        customer_message=customer_out,
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
            audio_url=_audio_url(conversation_id, assistant_message.id) if tts else None,
            sources=[
                MessageSourceOut(
                    chunk_id=s.chunk_id, document_id=s.document_id, similarity=s.similarity
                )
                for s in answer.sources
            ],
        ),
    )


def _audio_url(conversation_id: uuid.UUID, message_id: uuid.UUID) -> str:
    return (
        f"{settings.API_V1_PREFIX}/conversations/{conversation_id}"
        f"/messages/{message_id}/audio"
    )


def _owned_conversation_ids(
    db: Session, conversation_id: uuid.UUID, current_user: User
) -> tuple[uuid.UUID, uuid.UUID]:
    conversation = _get_owned_conversation(db, conversation_id, current_user)
    conv_id, org_id = conversation.id, conversation.organization_id
    db.rollback()  # release the connection during the LLM calls that follow
    return conv_id, org_id


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
