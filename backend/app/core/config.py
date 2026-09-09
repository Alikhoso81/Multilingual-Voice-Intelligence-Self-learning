from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .../backend  — used to anchor default file-storage paths so the app runs the
# same whether it's launched from a Docker image (WORKDIR /code) or straight from
# a local checkout.
BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """
    Central app configuration. All values come from environment variables
    (see .env.example). Never hardcode secrets here.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    PROJECT_NAME: str = "Multilingual Voice Intelligence Platform"
    API_V1_PREFIX: str = "/api/v1"

    # File storage. Defaults to backend/storage/... locally and /code/storage/...
    # inside the container (both resolve from BACKEND_DIR). Override with the
    # STORAGE_DIR env var if you want uploads somewhere else.
    STORAGE_DIR: Path = BACKEND_DIR / "storage"

    @property
    def audio_storage_dir(self) -> Path:
        return self.STORAGE_DIR / "audio"

    @property
    def document_storage_dir(self) -> Path:
        return self.STORAGE_DIR / "documents"

    @property
    def tts_storage_dir(self) -> Path:
        return self.STORAGE_DIR / "tts"

    # Database
    DATABASE_URL: str = (
        "postgresql+psycopg2://vip_user:vip_pass@db:5432/vip_db"
    )

    # Auth
    SECRET_KEY: str = "change-me-in-env-file"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8  # 8 hours
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # CORS
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]

    ENV: str = "development"

    # --- Security hardening (Phase 10) ---
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_PER_MINUTE: int = 120          # per client IP, across all endpoints
    AUTH_RATE_LIMIT_PER_MINUTE: int = 10      # tighter cap on /auth/login and /auth/register
    MAX_UPLOAD_MB: int = 25
    # When false, POST /organizations and POST /auth/register require an admin token
    # (set false in production; a first admin is seeded out of band).
    ALLOW_OPEN_REGISTRATION: bool = True

    @property
    def is_production(self) -> bool:
        return self.ENV.lower() in ("production", "prod", "staging")

    # --- RAG retrieval (Phase 3/4) ---
    EMBEDDING_MODEL_NAME: str = "intfloat/multilingual-e5-large"
    RAG_TOP_K: int = 5
    # Best-match cosine similarity (0..1) required before the LLM is allowed to
    # answer. Below this the system refuses and offers a human handoff instead of
    # guessing — a hard requirement from the spec (no hallucinated answers).
    # 0.78 separates a real match (~0.80+) from unrelated text (~0.74) for
    # multilingual-e5-large; Phase 10's eval harness should calibrate it on real data.
    RAG_CONFIDENCE_THRESHOLD: float = 0.78

    # --- Question clustering (Phase 8) ---
    # Cosine similarity for two customer questions to land in the same cluster.
    # multilingual-e5 scores short same-language questions high even when the
    # topic differs, so this sits near the top of the band (paraphrases ~0.90+).
    CLUSTER_SIMILARITY_THRESHOLD: float = 0.89
    # A cluster is a knowledge gap when its best KB match is below this. Kept
    # slightly ABOVE RAG_CONFIDENCE_THRESHOLD (surface gaps a little more eagerly
    # than the bot refuses) and clear of multilingual-e5's ~0.78 similarity floor.
    GAP_SIMILARITY_THRESHOLD: float = 0.80

    # --- LLM answer generation (Phase 4) ---
    # Which provider actually generates the grounded answer:
    #   "google"    -> Gemini      (GOOGLE_API_KEY, GEMINI_MODEL)
    #   "anthropic" -> Claude      (ANTHROPIC_API_KEY, ANTHROPIC_MODEL)
    #   "mock"      -> canned reply, no network — for tests / offline dev
    LLM_PROVIDER: str = "google"
    LLM_MAX_OUTPUT_TOKENS: int = 1024
    LLM_TEMPERATURE: float = 0.2

    GOOGLE_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"

    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-sonnet-5"

    # --- Text-to-speech (Phase 6) ---
    # TTS_PROVIDER: google | mock
    TTS_PROVIDER: str = "google"
    # Synthesize the assistant reply automatically when the customer sent voice.
    TTS_AUTOSPEAK_VOICE_REPLIES: bool = True
    GEMINI_TTS_MODEL: str = "gemini-2.5-flash-preview-tts"
    TTS_VOICE: str = "Kore"  # a prebuilt Gemini voice name


settings = Settings()
