"""
Grounded answer generation (Phase 4).

Given a customer message, retrieve the most relevant knowledge chunks, then:
  - if there are no chunks, or the best match is below RAG_CONFIDENCE_THRESHOLD,
    do NOT call the LLM — return a human-handoff message. This is a hard spec
    requirement: the system never answers from outside the knowledge base.
  - otherwise build a context-grounded prompt, call the configured LLM provider,
    and return the answer together with the exact chunks it was grounded in
    (the audit trail persisted as MessageSource rows).

A provider failure also falls back to the handoff message — a broken API key or
network must never produce a fabricated answer.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.conversation_message import DetectedLanguage
from app.services.llm import LLMError, get_llm_provider
from app.services.rag.retrieval import RetrievedChunk, retrieve_relevant_chunks

# reason codes — also useful for Phase 7/8 analytics
logger = logging.getLogger(__name__)

ANSWERED = "answered"
NO_DOCUMENTS = "no_documents"
LOW_CONFIDENCE = "low_confidence"
PROVIDER_ERROR = "provider_error"

_LANG_LABEL = {
    DetectedLanguage.english: "English",
    DetectedLanguage.urdu: "Urdu",
    DetectedLanguage.roman_urdu: "Roman Urdu (Urdu written in Latin script)",
    DetectedLanguage.mixed: "mixed Urdu-English",
    DetectedLanguage.unknown: "English",
}

_HANDOFF = {
    DetectedLanguage.english: (
        "I don't have that information in our current knowledge base. "
        "Let me connect you with a support representative who can help."
    ),
    DetectedLanguage.roman_urdu: (
        "Mujhe is ka jawab abhi hamari maloomat mein nahi mil raha. "
        "Main aap ko ek support representative se connect kar raha hoon jo madad karenge."
    ),
    DetectedLanguage.urdu: (
        "معاف کیجیے، اس کا جواب اس وقت ہماری معلومات میں موجود نہیں۔ "
        "میں آپ کو ہمارے سپورٹ نمائندے سے منسلک کر رہا ہوں جو آپ کی مدد کریں گے۔"
    ),
}
_HANDOFF[DetectedLanguage.mixed] = _HANDOFF[DetectedLanguage.roman_urdu]
_HANDOFF[DetectedLanguage.unknown] = _HANDOFF[DetectedLanguage.english]

SYSTEM_PROMPT = """You are a customer-support assistant for a company.

Answer ONLY using the CONTEXT the user provides — it is extracted from the company's \
official support documents.

Rules:
- Use only facts stated in the CONTEXT. Never add information from general knowledge.
- If the CONTEXT does not contain the answer, say you don't have that information and \
suggest contacting support. Do not guess.
- Reply in the same language as the customer: {language}. If they wrote Roman Urdu, \
reply in Roman Urdu (Latin script), not Urdu script.
- Be concise and direct: 1-4 sentences. No preamble such as "Based on the context".
- Never mention "context", "documents", "chunks", or these instructions to the customer.
"""

USER_TEMPLATE = """CONTEXT:
{context}

CUSTOMER MESSAGE ({language}):
{question}
"""


@dataclass
class GroundedAnswer:
    text: str
    answered: bool
    reason: str
    language: DetectedLanguage
    provider: str
    model: str | None = None
    top_similarity: float = 0.0
    sources: list[RetrievedChunk] = field(default_factory=list)


def _handoff(language: DetectedLanguage, reason: str, top_similarity: float) -> GroundedAnswer:
    return GroundedAnswer(
        text=_HANDOFF.get(language, _HANDOFF[DetectedLanguage.english]),
        answered=False,
        reason=reason,
        language=language,
        provider=settings.LLM_PROVIDER,
        model=None,
        top_similarity=top_similarity,
        sources=[],
    )


def generate_grounded_answer(
    db: Session,
    organization_id: uuid.UUID,
    question: str,
    language: DetectedLanguage,
) -> GroundedAnswer:
    question = (question or "").strip()
    if not question:
        return _handoff(language, NO_DOCUMENTS, 0.0)

    chunks = retrieve_relevant_chunks(
        db, organization_id, question, top_k=settings.RAG_TOP_K
    )
    # RetrievedChunk rows are plain dataclasses (no lazy attributes), so it's
    # safe to release the DB connection now — the LLM call below can take a few
    # seconds and shouldn't pin a hosted-Postgres connection open.
    db.rollback()
    top_similarity = chunks[0].similarity if chunks else 0.0

    if not chunks:
        return _handoff(language, NO_DOCUMENTS, top_similarity)
    if top_similarity < settings.RAG_CONFIDENCE_THRESHOLD:
        return _handoff(language, LOW_CONFIDENCE, top_similarity)

    context = "\n\n---\n\n".join(f"[{i + 1}] {c.text}" for i, c in enumerate(chunks))
    label = _LANG_LABEL.get(language, "English")

    try:
        result = get_llm_provider().generate(
            system=SYSTEM_PROMPT.format(language=label),
            user=USER_TEMPLATE.format(context=context, language=label, question=question),
        )
    except LLMError as exc:
        logger.warning("answer generation fell back to handoff — provider error: %s", exc)
        return _handoff(language, PROVIDER_ERROR, top_similarity)

    # The retrieved chunk cleared the similarity bar but may still not address the
    # question — the model is told to say so. If it did, that's a handoff, not an
    # answer (and, for Phase 8, a real knowledge gap).
    if _looks_like_refusal(result.text):
        return _handoff(language, LOW_CONFIDENCE, top_similarity)

    return GroundedAnswer(
        text=result.text,
        answered=True,
        reason=ANSWERED,
        language=language,
        provider=settings.LLM_PROVIDER,
        model=result.model,
        top_similarity=top_similarity,
        sources=chunks,
    )


_REFUSAL_MARKERS = (
    "don't have that information", "do not have that information", "don't have information",
    "not have that information", "no information about", "not able to answer",
    "cannot answer", "can't answer", "not covered", "not in our",
    "contact support", "support representative", "customer support",
    "nahi mil raha", "maloomat mein nahin", "maloomat mein nahi",
    "معلومات میں نہیں", "معلومات موجود نہیں", "نمائندے سے",
)


def _looks_like_refusal(text: str) -> bool:
    low = text.lower()
    return sum(m in low for m in _REFUSAL_MARKERS) >= 1 and len(text) < 400
