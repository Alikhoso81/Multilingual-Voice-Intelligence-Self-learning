"""
Speech-to-text service using Faster-Whisper.

Model is loaded ONCE per process (module-level singleton) and reused across
requests — loading it per-request would be far too slow. For an FYP/demo
scale, the "small" model is a reasonable accuracy/speed/VRAM tradeoff; drop to
"base" or "tiny" if your machine has no GPU and CPU inference is too slow, or
go up to "medium"/"large-v3" for better Urdu accuracy if you have the hardware.
This is exactly the kind of empirical choice flagged in the architecture doc —
test 2-3 model sizes on your own Urdu/Roman-Urdu samples and see what's usable.
"""
import os
from dataclasses import dataclass
from functools import lru_cache

from faster_whisper import WhisperModel

WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "small")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")  # "cuda" if a GPU is available
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")  # int8 is fastest on CPU


@dataclass
class TranscriptionResult:
    text: str
    whisper_language: str  # raw language code Whisper reported, e.g. "en", "ur"
    whisper_language_probability: float
    avg_logprob_confidence: float  # rough proxy for ASR confidence, 0-1 normalized
    duration_seconds: float


@lru_cache(maxsize=1)
def _get_model() -> WhisperModel:
    return WhisperModel(WHISPER_MODEL_SIZE, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE_TYPE)


def transcribe_audio(audio_path: str) -> TranscriptionResult:
    """
    Transcribe an audio file at `audio_path` (any format ffmpeg can decode:
    wav, mp3, m4a, ogg, etc — Faster-Whisper/ffmpeg handles the decoding).
    """
    model = _get_model()

    segments, info = model.transcribe(
        audio_path,
        beam_size=5,
        vad_filter=True,  # trims silence, helps with noisy customer-call audio
    )

    segment_list = list(segments)
    full_text = " ".join(s.text.strip() for s in segment_list).strip()

    if segment_list:
        avg_logprob = sum(s.avg_logprob for s in segment_list) / len(segment_list)
        # avg_logprob is typically in range [-1, 0]; map to a rough 0-1 confidence.
        confidence = max(0.0, min(1.0, 1.0 + avg_logprob))
    else:
        confidence = 0.0

    return TranscriptionResult(
        text=full_text,
        whisper_language=info.language,
        whisper_language_probability=info.language_probability,
        avg_logprob_confidence=confidence,
        duration_seconds=info.duration,
    )
