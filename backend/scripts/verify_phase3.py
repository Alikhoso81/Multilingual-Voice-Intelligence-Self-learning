"""
Phase 3 end-to-end verification — run against a live server + real database.

Covers the happy path AND the boundaries the project's testing philosophy asks
for: RBAC (403/401), input validation, cross-tenant isolation, cascade delete.

Usage (from backend/, with the venv active and uvicorn running on :8000):
    python scripts/verify_phase3.py
"""
from __future__ import annotations

import io
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/ on path

import requests
from sqlalchemy import create_engine, text

from app.core.config import settings

ROOT = os.getenv("VIP_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
BASE = f"{ROOT}/api/v1"

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(name)
    mark = "PASS" if condition else "FAIL"
    line = f"[{mark}] {name}"
    if detail and not condition:
        line += f"  -> {detail}"
    print(line)


def register(org_id: str, email: str, password: str, role: str) -> None:
    r = requests.post(
        f"{BASE}/auth/register",
        json={
            "organization_id": org_id,
            "full_name": email.split("@")[0],
            "email": email,
            "password": password,
            "role": role,
        },
        timeout=30,
    )
    r.raise_for_status()


def login(email: str, password: str) -> str:
    r = requests.post(
        f"{BASE}/auth/login",
        data={"username": email, "password": password},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


FAQ_TEXT = """\
ACME Telecom — Customer FAQ

How do I check my account balance?
Dial *123# from your ACME SIM, or open the ACME app and tap "Balance" on the
home screen. Your remaining balance and its expiry date are shown there.

Why is my internet package not activating?
A new data package can take up to 15 minutes to activate. If it still has not
activated after that, make sure your account balance covers the package price,
then restart your phone. If the problem continues, the package may be blocked
because a previous bundle is still active.

How do I port my number to ACME?
Send an SMS with the word PORT to 667 from the number you want to bring over.
You will receive a confirmation code and porting completes within 48 hours.

What are the customer support hours?
Phone support runs 24/7. Live chat in the ACME app is available 8am to midnight.
"""


def main() -> int:
    # 0. health
    r = requests.get(f"{ROOT}/health", timeout=10)
    check("health endpoint responds", r.status_code == 200, str(r.status_code))

    suffix = uuid.uuid4().hex[:8]

    # 1. two orgs
    org_a = requests.post(f"{BASE}/organizations", json={"name": f"OrgA-{suffix}", "industry": "telecom"}, timeout=30)
    org_b = requests.post(f"{BASE}/organizations", json={"name": f"OrgB-{suffix}", "industry": "banking"}, timeout=30)
    check("create org A", org_a.status_code == 201, org_a.text)
    check("create org B", org_b.status_code == 201, org_b.text)
    org_a_id, org_b_id = org_a.json()["id"], org_b.json()["id"]

    # 2. users
    pw = "TestPass123!"
    a_admin = f"admin-{suffix}@a.com"
    a_agent = f"agent-{suffix}@a.com"
    b_admin = f"admin-{suffix}@b.com"
    register(org_a_id, a_admin, pw, "admin")
    register(org_a_id, a_agent, pw, "agent")
    register(org_b_id, b_admin, pw, "admin")

    # 2a. duplicate email rejected
    dup = requests.post(
        f"{BASE}/auth/register",
        json={"organization_id": org_a_id, "full_name": "x", "email": a_admin, "password": pw, "role": "admin"},
        timeout=30,
    )
    check("duplicate email registration -> 400", dup.status_code == 400, str(dup.status_code))

    t_a_admin = login(a_admin, pw)
    t_a_agent = login(a_agent, pw)
    t_b_admin = login(b_admin, pw)

    # 3. auth boundaries
    no_tok = requests.get(f"{BASE}/knowledge/documents", timeout=30)
    check("list documents without token -> 401", no_tok.status_code == 401, str(no_tok.status_code))
    bad_tok = requests.get(f"{BASE}/knowledge/documents", headers=auth("garbage"), timeout=30)
    check("list documents with bad token -> 401", bad_tok.status_code == 401, str(bad_tok.status_code))

    # 4. RBAC on upload
    agent_upload = requests.post(
        f"{BASE}/knowledge/documents",
        headers=auth(t_a_agent),
        files={"file": ("faq.txt", io.BytesIO(FAQ_TEXT.encode()), "text/plain")},
        timeout=120,
    )
    check("agent uploads document -> 403", agent_upload.status_code == 403, str(agent_upload.status_code))

    # 5. validation: unsupported type
    bad_type = requests.post(
        f"{BASE}/knowledge/documents",
        headers=auth(t_a_admin),
        files={"file": ("logo.png", io.BytesIO(b"\x89PNG\r\n\x1a\n"), "image/png")},
        timeout=60,
    )
    check("admin uploads .png -> 400", bad_type.status_code == 400, str(bad_type.status_code))

    # 6. happy path upload (this triggers the embedding-model download on first run)
    print("\n... uploading FAQ; first run downloads the embedding model (~2.2GB), be patient ...\n")
    up = requests.post(
        f"{BASE}/knowledge/documents",
        headers=auth(t_a_admin),
        files={"file": ("acme_faq.txt", io.BytesIO(FAQ_TEXT.encode()), "text/plain")},
        timeout=3600,
    )
    check("admin uploads .txt -> 201", up.status_code == 201, up.text)
    doc = up.json() if up.status_code == 201 else {}
    doc_id = doc.get("id")
    check("uploaded document status == ready", doc.get("status") == "ready", str(doc))
    check("uploaded document has chunks", (doc.get("chunk_count") or 0) >= 1, str(doc.get("chunk_count")))

    # 7. list — org A sees it, org B does not
    list_a = requests.get(f"{BASE}/knowledge/documents", headers=auth(t_a_admin), timeout=30).json()
    check("org A lists its document", any(d["id"] == doc_id for d in list_a), str(list_a))
    list_b = requests.get(f"{BASE}/knowledge/documents", headers=auth(t_b_admin), timeout=30).json()
    check("org B does NOT see org A's document (tenant isolation)", all(d["id"] != doc_id for d in list_b), str(list_b))

    # 8. retrieval — relevant query returns sensible chunk
    s = requests.post(
        f"{BASE}/knowledge/search",
        headers=auth(t_a_admin),
        json={"query": "how do I check my account balance?", "top_k": 3},
        timeout=120,
    )
    check("search returns 200", s.status_code == 200, s.text)
    hits = s.json() if s.status_code == 200 else []
    check("search returns at least one chunk", len(hits) >= 1, str(hits))
    if hits:
        top = hits[0]
        check("top similarity in (0, 1]", 0.0 < top["similarity"] <= 1.0, str(top["similarity"]))
        check(
            "top chunk is about balance (semantic match)",
            "balance" in top["text"].lower() or "*123#" in top["text"],
            top["text"][:200],
        )

    # 9. retrieval is tenant-scoped — org B gets nothing
    s_b = requests.post(
        f"{BASE}/knowledge/search",
        headers=auth(t_b_admin),
        json={"query": "how do I check my account balance?", "top_k": 3},
        timeout=120,
    )
    check("org B search returns no chunks (tenant isolation)", s_b.json() == [], str(s_b.json()))

    # 10. delete RBAC + cascade
    del_agent = requests.delete(f"{BASE}/knowledge/documents/{doc_id}", headers=auth(t_a_agent), timeout=30)
    check("agent deletes document -> 403", del_agent.status_code == 403, str(del_agent.status_code))

    del_admin = requests.delete(f"{BASE}/knowledge/documents/{doc_id}", headers=auth(t_a_admin), timeout=30)
    check("admin deletes document -> 204", del_admin.status_code == 204, str(del_admin.status_code))

    engine = create_engine(settings.DATABASE_URL)
    with engine.connect() as c:
        remaining = c.execute(
            text("select count(*) from knowledge_chunks where document_id = :d"), {"d": doc_id}
        ).scalar()
    check("chunks cascade-deleted with document", remaining == 0, f"{remaining} chunks left")

    del_missing = requests.delete(f"{BASE}/knowledge/documents/{uuid.uuid4()}", headers=auth(t_a_admin), timeout=30)
    check("delete nonexistent document -> 404", del_missing.status_code == 404, str(del_missing.status_code))

    print(f"\n{'=' * 50}")
    print(f"PASSED: {len(PASSED)}   FAILED: {len(FAILED)}")
    if FAILED:
        print("FAILED:", ", ".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
