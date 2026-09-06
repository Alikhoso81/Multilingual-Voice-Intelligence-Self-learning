"""Google Gemini TTS provider (default). Uses the same GOOGLE_API_KEY as the LLM.

Gemini's TTS models return raw little-endian PCM (`audio/L16;codec=pcm;rate=N`);
we wrap it in a WAV container so it's a normal playable file.
"""
from __future__ import annotations

import io
import re
import wave
from functools import lru_cache

from app.core.config import settings
from app.services.tts.base import TTSError, TTSProvider, TTSResult

_RATE_RE = re.compile(r"rate=(\d+)")


@lru_cache(maxsize=1)
def _client():
    if not settings.GOOGLE_API_KEY:
        raise TTSError("GOOGLE_API_KEY is not set — add it to backend/.env")
    from google import genai

    return genai.Client(api_key=settings.GOOGLE_API_KEY)


def _pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)  # 16-bit
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


class GoogleTTSProvider(TTSProvider):
    name = "google"

    def synthesize(self, *, text: str) -> TTSResult:
        from google.genai import types

        try:
            resp = _client().models.generate_content(
                model=settings.GEMINI_TTS_MODEL,
                contents=text,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=settings.TTS_VOICE
                            )
                        )
                    ),
                ),
            )
            part = resp.candidates[0].content.parts[0].inline_data
            pcm, mime = part.data, part.mime_type or ""
        except TTSError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise TTSError(f"Gemini TTS request failed: {exc}") from exc

        if not pcm:
            raise TTSError("Gemini TTS returned no audio")

        match = _RATE_RE.search(mime)
        sample_rate = int(match.group(1)) if match else 24000
        return TTSResult(
            wav_bytes=_pcm_to_wav(pcm, sample_rate),
            duration_seconds=round(len(pcm) / 2 / sample_rate, 2),
        )
