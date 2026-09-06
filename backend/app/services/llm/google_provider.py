"""Google Gemini provider (default). SDK: `google-genai`."""
from __future__ import annotations

from functools import lru_cache

from app.core.config import settings
from app.services.llm.base import LLMError, LLMProvider, LLMResult


@lru_cache(maxsize=1)
def _client():
    if not settings.GOOGLE_API_KEY:
        raise LLMError("GOOGLE_API_KEY is not set — add it to backend/.env")
    from google import genai  # imported lazily so the app starts without the key

    return genai.Client(api_key=settings.GOOGLE_API_KEY)


class GoogleProvider(LLMProvider):
    name = "google"

    def generate(self, *, system: str, user: str) -> LLMResult:
        from google.genai import types

        try:
            resp = _client().models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    temperature=settings.LLM_TEMPERATURE,
                    max_output_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
                ),
            )
        except LLMError:
            raise
        except Exception as exc:  # noqa: BLE001 — normalize every SDK/network error
            raise LLMError(f"Gemini request failed: {exc}") from exc

        text = (getattr(resp, "text", None) or "").strip()
        if not text:
            raise LLMError("Gemini returned an empty response")
        return LLMResult(text=text, model=settings.GEMINI_MODEL)
