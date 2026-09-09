"""Google Gemini provider (default). SDK: `google-genai`."""
from __future__ import annotations

import time
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

        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=settings.LLM_TEMPERATURE,
            max_output_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
        )
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = _client().models.generate_content(
                    model=settings.GEMINI_MODEL, contents=user, config=config
                )
                break
            except LLMError:
                raise
            except Exception as exc:  # noqa: BLE001 — normalize every SDK/network error
                last_exc = exc
                # 503 "model overloaded" is transient; 429 (quota) is not — surface it.
                if "503" in str(exc) and attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise LLMError(f"Gemini request failed: {exc}") from exc
        else:  # pragma: no cover
            raise LLMError(f"Gemini request failed: {last_exc}")

        text = (getattr(resp, "text", None) or "").strip()
        if not text:
            raise LLMError("Gemini returned an empty response")
        return LLMResult(text=text, model=settings.GEMINI_MODEL)
