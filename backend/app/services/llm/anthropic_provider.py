"""Anthropic Claude provider.

The original project spec names Claude as the LLM; this keeps that path a
config switch away. Requires `pip install anthropic` (not in requirements.txt by
default — the deployed provider is Gemini). Set LLM_PROVIDER=anthropic and
ANTHROPIC_API_KEY to use it.
"""
from __future__ import annotations

from functools import lru_cache

from app.core.config import settings
from app.services.llm.base import LLMError, LLMProvider, LLMResult


@lru_cache(maxsize=1)
def _client():
    if not settings.ANTHROPIC_API_KEY:
        raise LLMError("ANTHROPIC_API_KEY is not set — add it to backend/.env")
    try:
        import anthropic
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise LLMError(
            "anthropic package not installed — run: uv pip install --python .venv anthropic"
        ) from exc
    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def generate(self, *, system: str, user: str) -> LLMResult:
        try:
            msg = _client().messages.create(
                model=settings.ANTHROPIC_MODEL,
                max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except LLMError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Claude request failed: {exc}") from exc

        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text").strip()
        if not text:
            raise LLMError("Claude returned an empty response")
        return LLMResult(text=text, model=settings.ANTHROPIC_MODEL)
