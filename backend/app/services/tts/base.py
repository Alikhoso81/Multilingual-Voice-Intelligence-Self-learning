"""Provider-agnostic text-to-speech interface (Phase 6)."""
from __future__ import annotations

from dataclasses import dataclass


class TTSError(RuntimeError):
    """Any failure synthesizing speech. Callers treat it as 'no audio' — the
    text reply is unaffected."""


@dataclass
class TTSResult:
    wav_bytes: bytes            # a complete WAV file (header + PCM)
    duration_seconds: float


class TTSProvider:
    name: str = "base"

    def synthesize(self, *, text: str) -> TTSResult:
        raise NotImplementedError
