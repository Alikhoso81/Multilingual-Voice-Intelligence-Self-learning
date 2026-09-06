"""Provider-agnostic LLM interface.

Phase 4 only needs text-in / text-out. Keeping the surface this small means the
answer-generation logic in `answering.py` never imports a vendor SDK, and swapping
Gemini <-> Claude <-> a local model is a one-line config change (`LLM_PROVIDER`).
"""
from __future__ import annotations

from dataclasses import dataclass


class LLMError(RuntimeError):
    """Any failure producing a completion — missing key, network, empty output.

    Callers treat this as 'no answer available' and fall back to a human handoff
    rather than surfacing an error or fabricating a reply.
    """


@dataclass
class LLMResult:
    text: str
    model: str


class LLMProvider:
    name: str = "base"

    def generate(self, *, system: str, user: str) -> LLMResult:
        raise NotImplementedError
