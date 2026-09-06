from app.core.config import settings
from app.services.llm.base import LLMError, LLMProvider, LLMResult

__all__ = ["LLMProvider", "LLMResult", "LLMError", "get_llm_provider"]


def get_llm_provider() -> LLMProvider:
    """Return the provider selected by settings.LLM_PROVIDER.

    Constructed per call (cheap); each provider caches its own SDK client.
    """
    provider = settings.LLM_PROVIDER.lower().strip()
    if provider == "google":
        from app.services.llm.google_provider import GoogleProvider

        return GoogleProvider()
    if provider == "anthropic":
        from app.services.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider()
    if provider == "mock":
        from app.services.llm.mock_provider import MockProvider

        return MockProvider()
    raise LLMError(
        f"Unknown LLM_PROVIDER {settings.LLM_PROVIDER!r} — use google | anthropic | mock"
    )
