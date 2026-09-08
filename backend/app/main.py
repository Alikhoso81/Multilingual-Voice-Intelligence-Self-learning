import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1 import (
    auth,
    conversations,
    dashboard,
    knowledge,
    learning,
    organizations,
    users,
)
from app.core.config import BACKEND_DIR, settings
from app.core.middleware import RateLimitMiddleware, SecurityHeadersMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_DEFAULT_SECRET = "change-me-in-env-file"
if settings.is_production and settings.SECRET_KEY in ("", _DEFAULT_SECRET):
    raise RuntimeError("SECRET_KEY must be set to a strong random value in production")
if settings.SECRET_KEY in ("", _DEFAULT_SECRET):
    logger.warning("SECRET_KEY is the default — fine for local dev, never for production")

app = FastAPI(title=settings.PROJECT_NAME, openapi_url=f"{settings.API_V1_PREFIX}/openapi.json")

# Order matters: last added runs first. Rate limit -> security headers -> CORS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)

app.include_router(organizations.router, prefix=settings.API_V1_PREFIX)
app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(users.router, prefix=settings.API_V1_PREFIX)
app.include_router(conversations.router, prefix=settings.API_V1_PREFIX)
app.include_router(knowledge.router, prefix=settings.API_V1_PREFIX)
app.include_router(learning.router, prefix=settings.API_V1_PREFIX)
app.include_router(dashboard.router, prefix=settings.API_V1_PREFIX)


@app.get("/health", tags=["health"])
def health_check() -> dict:
    return {"status": "ok", "service": settings.PROJECT_NAME}


# Phase 9 — the admin/agent dashboard (static single-page app at /app/)
_WEB_DIR = BACKEND_DIR / "app" / "web"
if _WEB_DIR.is_dir():
    app.mount("/app", StaticFiles(directory=str(_WEB_DIR), html=True), name="web")
