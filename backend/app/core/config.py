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


settings = Settings()
