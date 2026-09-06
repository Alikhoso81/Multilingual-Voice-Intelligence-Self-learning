"""Offline TTS provider — returns a short silent WAV so the audio path
(synthesize -> save -> serve) can be tested without an API key."""
from __future__ import annotations

import io
import wave

from app.services.tts.base import TTSProvider, TTSResult

_SAMPLE_RATE = 24000
_SECONDS = 0.4


def _silent_wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(_SAMPLE_RATE)
        w.writeframes(b"\x00\x00" * int(_SAMPLE_RATE * _SECONDS))
    return buf.getvalue()


class MockTTSProvider(TTSProvider):
    name = "mock"

    def synthesize(self, *, text: str) -> TTSResult:
        return TTSResult(wav_bytes=_silent_wav(), duration_seconds=_SECONDS)
