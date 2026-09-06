"""Deterministic offline provider for tests and no-key development.

It doesn't call any model — it stitches a short answer out of the context it was
handed, so the full retrieve -> ground -> answer -> cite-sources pipeline can be
exercised end to end without an API key or network access.
"""
from __future__ import annotations

import json

from app.services.llm.base import LLMProvider, LLMResult

_CONTEXT_MARKER = "CONTEXT:"
_QUESTION_MARKER = "CUSTOMER MESSAGE"

# One object that satisfies every JSON caller (intent classification,
# conversation analytics) — each parser reads only the keys it needs.
_MOCK_JSON = json.dumps(
    {
        "intent": "general_inquiry",
        "confidence": 0.5,
        "entities": {
            "phone_numbers": [],
            "amounts": [],
            "package_or_product_names": [],
            "dates_or_times": [],
            "account_or_order_ids": [],
            "locations": [],
        },
        "summary": "[mock] The customer asked a question and the assistant responded.",
        "sentiment": "neutral",
        "resolution": "resolved",
        "follow_up": "none",
    }
)


class MockProvider(LLMProvider):
    name = "mock"

    def generate(self, *, system: str, user: str) -> LLMResult:
        if "JSON" in system or "json" in system:
            return LLMResult(text=_MOCK_JSON, model="mock")

        context = user
        if _CONTEXT_MARKER in user:
            context = user.split(_CONTEXT_MARKER, 1)[1]
        if _QUESTION_MARKER in context:
            context = context.split(_QUESTION_MARKER, 1)[0]

        snippet = ""
        for line in context.splitlines():
            line = line.strip().lstrip("[]0123456789 ").strip()
            if len(line) > 40:
                snippet = line
                break

        return LLMResult(
            text=f"[mock] According to the company documents: {snippet}"
            if snippet
            else "[mock] The company documents cover this — please see the cited sections.",
            model="mock",
        )
