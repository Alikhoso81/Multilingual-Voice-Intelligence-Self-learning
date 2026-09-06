"""
Conversation analytics (Phase 7): one LLM pass over a transcript produces a
short summary, the customer's overall sentiment, and a resolution assessment.

Used by the admin/agent dashboards (Phase 9) and business-impact metrics
(Phase 10). A failure returns ok=False and the conversation is left un-analyzed.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from app.models.conversation import ConversationResolution, ConversationSentiment
from app.models.conversation_message import Message, MessageRole
from app.services.llm import LLMError, get_llm_provider

logger = logging.getLogger(__name__)

_SENTIMENTS = {s.value for s in ConversationSentiment}
_RESOLUTIONS = {r.value for r in ConversationResolution}

_SYSTEM_PROMPT = """You analyze a customer-support conversation transcript. \
Messages are labelled CUSTOMER or ASSISTANT.

Return ONLY this JSON object (no markdown fence, no commentary):
{"summary": "<2-3 sentence summary in English of what the customer wanted and what happened>",
 "sentiment": "<positive | neutral | negative | frustrated>",
 "resolution": "<resolved | unresolved | needs_follow_up | escalated>",
 "follow_up": "<one short sentence: the next action a human should take, or \\"none\\">"}

resolution guidance:
- resolved: the customer's question was answered from the knowledge base
- unresolved: the customer did not get a usable answer
- needs_follow_up: partially answered; a human should check back
- escalated: the assistant handed off to a human representative
"""


@dataclass
class ConversationAnalysis:
    ok: bool
    summary: str | None = None
    sentiment: ConversationSentiment = ConversationSentiment.unknown
    resolution: ConversationResolution = ConversationResolution.unknown
    follow_up: str | None = None


_SPEAKER = {MessageRole.customer: "CUSTOMER", MessageRole.system: "ASSISTANT", MessageRole.agent: "AGENT"}


def render_transcript(messages: list[Message]) -> str:
    """Render messages to a plain CUSTOMER/ASSISTANT transcript. Call this while
    a DB session is available — `analyze_conversation` takes the string so the
    connection isn't held during the LLM call."""
    lines = [
        f"{_SPEAKER.get(m.role, 'AGENT')}: {(m.raw_text or '').strip()}"
        for m in messages
        if (m.raw_text or "").strip()
    ]
    return "\n".join(lines)


def _parse(raw: str) -> ConversationAnalysis:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    data = json.loads(match.group(0) if match else raw)

    summary = str(data.get("summary", "")).strip() or None

    sentiment_value = str(data.get("sentiment", "")).strip().lower()
    sentiment = (
        ConversationSentiment(sentiment_value)
        if sentiment_value in _SENTIMENTS
        else ConversationSentiment.unknown
    )

    resolution_value = str(data.get("resolution", "")).strip().lower()
    resolution = (
        ConversationResolution(resolution_value)
        if resolution_value in _RESOLUTIONS
        else ConversationResolution.unknown
    )

    follow_up = str(data.get("follow_up", "")).strip()
    if follow_up.lower() in ("", "none", "n/a"):
        follow_up = None

    return ConversationAnalysis(True, summary, sentiment, resolution, follow_up)


def analyze_conversation(transcript: str) -> ConversationAnalysis:
    transcript = (transcript or "").strip()
    if not transcript:
        return ConversationAnalysis(ok=False)

    try:
        result = get_llm_provider().generate(system=_SYSTEM_PROMPT, user=transcript)
        return _parse(result.text)
    except LLMError as exc:
        logger.warning("conversation analysis skipped — provider error: %s", exc)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("conversation analysis skipped — unparseable response: %s", exc)
    return ConversationAnalysis(ok=False)
