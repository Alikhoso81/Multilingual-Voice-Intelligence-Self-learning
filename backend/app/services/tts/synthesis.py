"""
Turn an assistant reply into a spoken WAV, saved under STORAGE_DIR/tts.

Wraps the provider with a per-language delivery instruction so Gemini pronounces
Roman Urdu as Urdu (not letter-by-letter English) and picks the right accent.
A failure here returns None — the text reply is never affected.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from app.core.config import settings
from app.models.conversation_message import DetectedLanguage
from app.services.tts import TTSError, get_tts_provider

logger = logging.getLogger(__name__)

_STYLE = {
    DetectedLanguage.english: (
        "Read this customer-support reply aloud in a clear, friendly Pakistani English voice:"
    ),
    DetectedLanguage.urdu: "Read this Urdu customer-support reply aloud clearly and naturally:",
    DetectedLanguage.roman_urdu: (
        "Read this aloud with natural Urdu pronunciation — it is Urdu written in Latin script, "
        "not English:"
    ),
    DetectedLanguage.mixed: "Read this aloud naturally, mixing Urdu and English pronunciation as written:",
    DetectedLanguage.unknown: "Read this customer-support reply aloud clearly:",
}


def synthesize_reply(text: str, language: DetectedLanguage) -> tuple[Path, float] | None:
    """Synthesize `text`, save a .wav, return (path, duration_seconds) or None on failure."""
    text = (text or "").strip()
    if not text:
        return None

    style = _STYLE.get(language, _STYLE[DetectedLanguage.unknown])
    try:
        result = get_tts_provider().synthesize(text=f"{style}\n\n{text}")
    except TTSError as exc:
        logger.warning("TTS synthesis skipped: %s", exc)
        return None

    settings.tts_storage_dir.mkdir(parents=True, exist_ok=True)
    path = settings.tts_storage_dir / f"{uuid.uuid4()}.wav"
    path.write_bytes(result.wav_bytes)
    return path, result.duration_seconds
