"""
Intent classification + entity extraction (Phase 5).

One LLM call per customer message, run through the same pluggable provider as
answer generation. It's auxiliary metadata — a failure here (LLM down, bad JSON)
never blocks the conversation: the message is stored with intent=unknown and no
entities.

The entity extraction is deliberately shallow (regex-style categories the model
fills in) — Phase 5 needs it queryable for routing and Phase 7/8 analytics, not
perfect. A dedicated NER model can replace this behind the same function later.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from app.models.conversation_message import DetectedLanguage, MessageIntent
from app.services.llm import LLMError, get_llm_provider

logger = logging.getLogger(__name__)

_VALID_INTENTS = {i.value for i in MessageIntent}

_ENTITY_KEYS = (
    "phone_numbers",
    "amounts",
    "package_or_product_names",
    "dates_or_times",
    "account_or_order_ids",
    "locations",
)

_SYSTEM_PROMPT = """You are the NLU component of a multilingual customer-support system \
(English, Urdu, Roman Urdu, mixed). Classify one customer message and extract entities.

Intent — pick exactly one:
- billing: charges, invoices, payments, refunds, "bill too high"
- technical_support: something is broken / not working / slow / no signal
- account_management: sign up, cancel, close, transfer, update details, SIM / number ops
- complaint: dissatisfaction, wants to escalate, angry about service
- sales_inquiry: prices, packages, plans, upgrades, "do you offer / sell ..."
- general_inquiry: opening hours, contact info, general how-to
- other: a valid message that fits none of the above

Entities — extract literal strings from the message into these lists (empty list if none):
phone_numbers, amounts, package_or_product_names, dates_or_times, account_or_order_ids, locations

Respond with ONLY this JSON object, no markdown fence, no commentary:
{"intent": "<one intent>", "confidence": <0.0-1.0>, "entities": {"phone_numbers": [], "amounts": [], "package_or_product_names": [], "dates_or_times": [], "account_or_order_ids": [], "locations": []}}
"""


@dataclass
class IntentResult:
    intent: MessageIntent
    confidence: float
    entities: dict[str, list[str]] = field(default_factory=dict)


def _empty_entities() -> dict[str, list[str]]:
    return {k: [] for k in _ENTITY_KEYS}


def _parse(raw: str) -> IntentResult:
    text = raw.strip()
    # tolerate ```json ... ``` fences and leading/trailing prose
    fence = re.search(r"\{.*\}", text, re.DOTALL)
    if fence:
        text = fence.group(0)
    data = json.loads(text)

    intent_value = str(data.get("intent", "")).strip().lower()
    intent = MessageIntent(intent_value) if intent_value in _VALID_INTENTS else MessageIntent.other

    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    raw_entities = data.get("entities") or {}
    entities = _empty_entities()
    if isinstance(raw_entities, dict):
        for key in _ENTITY_KEYS:
            value = raw_entities.get(key)
            if isinstance(value, list):
                entities[key] = [str(v).strip() for v in value if str(v).strip()]

    return IntentResult(intent=intent, confidence=confidence, entities=entities)


def classify_message(text: str, language: DetectedLanguage) -> IntentResult:
    text = (text or "").strip()
    if not text:
        return IntentResult(MessageIntent.unknown, 0.0, _empty_entities())

    try:
        result = get_llm_provider().generate(
            system=_SYSTEM_PROMPT,
            user=f"Message language: {language.value}\nMessage: {text}",
        )
        return _parse(result.text)
    except LLMError as exc:
        logger.warning("intent classification skipped — provider error: %s", exc)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("intent classification skipped — unparseable response: %s", exc)
    return IntentResult(MessageIntent.unknown, 0.0, _empty_entities())
