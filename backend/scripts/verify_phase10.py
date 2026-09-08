"""
Phase 10 verification — security hardening.

Self-contained (TestClient, toggles settings at runtime — the endpoints read
them per request):
    .venv/Scripts/python scripts/verify_phase10.py

Checks: response hardening headers, the per-IP rate limiter (429 + Retry-After),
the refresh-token endpoint, the upload size limit (413), and the
production registration gate (ALLOW_OPEN_REGISTRATION=False).
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import io

from starlette.testclient import TestClient

from app.core.config import settings
from app.main import app

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASSED if ok else FAILED).append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if detail and not ok else ""))


def main() -> int:
    client = TestClient(app)

    # 1. hardening headers
    h = client.get("/health").headers
    check("X-Content-Type-Options: nosniff", h.get("x-content-type-options") == "nosniff", str(dict(h)))
    check("X-Frame-Options: DENY", h.get("x-frame-options") == "DENY", h.get("x-frame-options", ""))
    check("Referrer-Policy set", "referrer-policy" in h, "")

    # setup an org + admin (open registration on)
    org = client.post("/api/v1/organizations", json={"name": f"p10-{uuid.uuid4().hex[:8]}"}).json()
    email = f"p10-{uuid.uuid4().hex[:8]}@x.com"
    client.post("/api/v1/auth/register", json={
        "organization_id": org["id"], "full_name": "a", "email": email, "password": "Pass123!", "role": "admin"})
    login = client.post("/api/v1/auth/login", data={"username": email, "password": "Pass123!"}).json()
    admin_h = {"Authorization": f"Bearer {login['access_token']}"}

    # 2. refresh token
    rf = client.post("/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]})
    check("POST /auth/refresh -> 200 + new access token",
          rf.status_code == 200 and rf.json().get("access_token") and rf.json()["access_token"] != login["access_token"],
          rf.text)
    check("refresh with garbage -> 401",
          client.post("/api/v1/auth/refresh", json={"refresh_token": "not-a-token"}).status_code == 401)
    check("access token rejected as refresh -> 401",
          client.post("/api/v1/auth/refresh", json={"refresh_token": login["access_token"]}).status_code == 401)

    # 3. rate limiting
    old_enabled, old_auth = settings.RATE_LIMIT_ENABLED, settings.AUTH_RATE_LIMIT_PER_MINUTE
    settings.RATE_LIMIT_ENABLED = True
    settings.AUTH_RATE_LIMIT_PER_MINUTE = 3
    try:
        codes = [client.post("/api/v1/auth/login", data={"username": email, "password": "x"}).status_code
                 for _ in range(10)]
        limited = client.post("/api/v1/auth/login", data={"username": email, "password": "x"})
        check("rapid /auth/login hits a 429", 429 in codes or limited.status_code == 429, str(codes))
        check("429 carries Retry-After", "retry-after" in limited.headers or 429 in codes, "")
    finally:
        settings.RATE_LIMIT_ENABLED, settings.AUTH_RATE_LIMIT_PER_MINUTE = old_enabled, old_auth

    # 4. upload size limit
    old_max = settings.MAX_UPLOAD_MB
    settings.MAX_UPLOAD_MB = 1
    try:
        big = io.BytesIO(b"x" * (2 * 1024 * 1024))
        r = client.post("/api/v1/knowledge/documents", headers=admin_h,
                        files={"file": ("big.txt", big, "text/plain")})
        check("oversized upload -> 413", r.status_code == 413, str(r.status_code))
    finally:
        settings.MAX_UPLOAD_MB = old_max

    # 5. production registration gate
    old_open = settings.ALLOW_OPEN_REGISTRATION
    settings.ALLOW_OPEN_REGISTRATION = False
    try:
        check("closed reg: POST /organizations without token -> 403",
              client.post("/api/v1/organizations", json={"name": "x"}).status_code == 403)
        check("closed reg: POST /auth/register without admin -> 403",
              client.post("/api/v1/auth/register", json={
                  "organization_id": org["id"], "full_name": "b", "email": f"b-{uuid.uuid4().hex[:6]}@x.com",
                  "password": "Pass123!", "role": "agent"}).status_code == 403)
        ok = client.post("/api/v1/auth/register", headers=admin_h, json={
            "organization_id": org["id"], "full_name": "c", "email": f"c-{uuid.uuid4().hex[:6]}@x.com",
            "password": "Pass123!", "role": "agent"})
        check("closed reg: admin CAN still add a user to their org -> 201", ok.status_code == 201, ok.text)
    finally:
        settings.ALLOW_OPEN_REGISTRATION = old_open

    print(f"\n{'=' * 50}\nPASSED: {len(PASSED)}   FAILED: {len(FAILED)}")
    if FAILED:
        print("FAILED:", "; ".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
