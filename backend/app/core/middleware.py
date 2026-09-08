"""
Security middleware (Phase 10): response hardening headers + a lightweight
per-IP rate limiter.

The rate limiter is an in-process sliding window — correct for a single worker.
Behind multiple workers / instances, move the counter to Redis (the container is
already in docker-compose).
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-XSS-Protection": "0",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        for key, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        if settings.is_production:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window limiter. /auth/* gets the tighter AUTH cap; /health and the
    static dashboard are exempt."""

    def __init__(self, app) -> None:
        super().__init__(app)
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _limit_for(self, path: str) -> int:
        if path.startswith(f"{settings.API_V1_PREFIX}/auth/"):
            return settings.AUTH_RATE_LIMIT_PER_MINUTE
        return settings.RATE_LIMIT_PER_MINUTE

    async def dispatch(self, request: Request, call_next) -> Response:
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)

        path = request.url.path
        if path == "/health" or path.startswith("/app"):
            return await call_next(request)

        client = request.client.host if request.client else "unknown"
        limit = self._limit_for(path)
        key = f"{client}:{'auth' if limit == settings.AUTH_RATE_LIMIT_PER_MINUTE else 'all'}"

        now = time.monotonic()
        window = self._hits[key]
        while window and window[0] <= now - 60:
            window.popleft()

        if len(window) >= limit:
            retry = max(1, int(60 - (now - window[0])))
            return JSONResponse(
                {"detail": "Rate limit exceeded. Slow down."},
                status_code=429,
                headers={"Retry-After": str(retry)},
            )

        window.append(now)
        return await call_next(request)
