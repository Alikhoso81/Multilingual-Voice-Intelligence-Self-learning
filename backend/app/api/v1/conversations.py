import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.models.conversation import Conversation
from app.models.conversation_message import Message, MessageRole, VoiceRecording
from app.models.user import User
from app.schemas.conversation import (
    ConversationCreate,
    ConversationOut,
    MessageOut,
    TextMessageCreate,
)
from app.services.speech.language_utils import detect_language, normalize_text
from app.services.speech.whisper_service import transcribe_audio

router = APIRouter(prefix="/conversations", tags=["conversations"])

AUDIO_STORAGE_DIR = Path("/code/storage/audio")
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


@router.post("/{conversation_id}/messages/text", response_model=MessageOut, status_code=201)
def send_text_message(
    conversation_id: uuid.UUID,
    payload: TextMessageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Message:
    conversation = _get_owned_conversation(db, conversation_id, current_user)

    language = detect_language(payload.text)
    normalized = normalize_text(payload.text, language)

    message = Message(
        conversation_id=conversation.id,
        role=MessageRole.customer,
        raw_text=payload.text,
        normalized_text=normalized,
        language=language,
        asr_confidence=None,  # not applicable to typed text
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


@router.post("/{conversation_id}/messages/voice", response_model=MessageOut, status_code=201)
async def send_voice_message(
    conversation_id: uuid.UUID,
    audio: UploadFile,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Message:
    """
    Accepts an audio file (wav/mp3/m4a/ogg), transcribes it with Faster-Whisper,
    runs language detection + normalization, and stores everything: the audio
    file reference, the raw transcript, the normalized text, and the detected
    language — exactly the fields the architecture spec calls for.
    """
    conversation = _get_owned_conversation(db, conversation_id, current_user)

    if not audio.filename:
        raise HTTPException(status_code=400, detail="No audio file provided")

    suffix = Path(audio.filename).suffix or ".wav"
    saved_filename = f"{uuid.uuid4()}{suffix}"
    saved_path = AUDIO_STORAGE_DIR / saved_filename

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

    message = Message(
        conversation_id=conversation.id,
        role=MessageRole.customer,
        raw_text=result.text,
        normalized_text=normalized,
        language=language,
        asr_confidence=result.avg_logprob_confidence,
    )
    db.add(message)
    db.flush()  # get message.id before creating the child row

    voice_recording = VoiceRecording(
        message_id=message.id,
        audio_path=str(saved_path),
        duration_seconds=result.duration_seconds,
    )
    db.add(voice_recording)
    db.commit()
    db.refresh(message)
    return message


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
