from app.core.config import settings
from app.services.tts.base import TTSError, TTSProvider, TTSResult

__all__ = ["TTSProvider", "TTSResult", "TTSError", "get_tts_provider"]


def get_tts_provider() -> TTSProvider:
    provider = settings.TTS_PROVIDER.lower().strip()
    if provider == "google":
        from app.services.tts.google_tts import GoogleTTSProvider

        return GoogleTTSProvider()
    if provider == "mock":
        from app.services.tts.mock_tts import MockTTSProvider

        return MockTTSProvider()
    raise TTSError(f"Unknown TTS_PROVIDER {settings.TTS_PROVIDER!r} — use google | mock")
