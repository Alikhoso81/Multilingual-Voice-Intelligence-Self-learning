"""
Phase 4 end-to-end verification — grounded answer generation + refusal.

Run against a live server (any LLM_PROVIDER; use `mock` for a no-key run) + real DB:
    LLM_PROVIDER=mock .venv/Scripts/uvicorn app.main:app --port 8001   # terminal 1
    VIP_BASE_URL=http://127.0.0.1:8001 .venv/Scripts/python scripts/verify_phase4.py

Checks: an in-KB question gets an answered=True reply grounded in real chunks
(MessageSource rows written); an out-of-KB question gets answered=False with the
human-handoff text and no sources; language propagates (Roman Urdu in -> Roman
Urdu out); the transcript shows both turns; another org with no documents always
gets a handoff; missing token -> 401.
"""
from __future__ import annotations

import io
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests
from sqlalchemy import create_engine, text

from app.core.config import settings

ROOT = os.getenv("VIP_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
BASE = f"{ROOT}/api/v1"

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(name)
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f"  -> {detail}" if detail and not condition else ""))


def register(org_id: str, email: str, password: str, role: str) -> None:
    r = requests.post(
        f"{BASE}/auth/register",
        json={"organization_id": org_id, "full_name": email.split("@")[0], "email": email,
              "password": password, "role": role},
        timeout=30,
    )
    r.raise_for_status()


def login(email: str, password: str) -> str:
    r = requests.post(f"{BASE}/auth/login", data={"username": email, "password": password}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


FAQ_TEXT = """\
ACME Telecom — Customer FAQ

How do I check my account balance?
Dial *123# from your ACME SIM, or open the ACME app and tap "Balance" on the home
screen. Your remaining balance and its expiry date are shown there.

Why is my internet package not activating?
A new data package can take up to 15 minutes to activate. Make sure your account
balance covers the package price, then restart your phone.

How do I port my number to ACME?
Send an SMS with the word PORT to 667 from the number you want to bring over.
"""


def main() -> int:
    suffix = uuid.uuid4().hex[:8]
    pw = "TestPass123!"

    org_a = requests.post(f"{BASE}/organizations", json={"name": f"A-{suffix}", "industry": "telecom"}, timeout=30).json()
    org_b = requests.post(f"{BASE}/organizations", json={"name": f"B-{suffix}", "industry": "telecom"}, timeout=30).json()
    a_admin, b_admin = f"a-{suffix}@x.com", f"b-{suffix}@x.com"
    register(org_a["id"], a_admin, pw, "admin")
    register(org_b["id"], b_admin, pw, "admin")
    t_a, t_b = login(a_admin, pw), login(b_admin, pw)

    # seed org A's knowledge base
    up = requests.post(
        f"{BASE}/knowledge/documents",
        headers=auth(t_a),
        files={"file": ("faq.txt", io.BytesIO(FAQ_TEXT.encode()), "text/plain")},
        timeout=600,
    )
    check("seed document ready", up.status_code == 201 and up.json().get("status") == "ready", up.text)

    conv = requests.post(f"{BASE}/conversations", headers=auth(t_a), json={"channel": "text"}, timeout=30)
    check("create conversation", conv.status_code == 201, conv.text)
    conv_id = conv.json()["id"]

    # --- 1. in-KB question -> grounded answer ---
    r = requests.post(
        f"{BASE}/conversations/{conv_id}/messages/text",
        headers=auth(t_a),
        json={"text": "How do I check my account balance?"},
        timeout=120,
    )
    check("in-KB message -> 201", r.status_code == 201, r.text)
    body = r.json() if r.status_code == 201 else {}
    cust, asst = body.get("customer_message", {}), body.get("assistant_message", {})
    check("customer_message stored with role=customer", cust.get("role") == "customer", str(cust))
    check("assistant_message role=system", asst.get("role") == "system", str(asst))
    check("in-KB answer answered=True", asst.get("answered") is True, str(asst))
    check("in-KB answer reason=answered", asst.get("reason") == "answered", str(asst.get("reason")))
    check("in-KB answer cites >=1 source", len(asst.get("sources") or []) >= 1, str(asst.get("sources")))
    check("each source has chunk_id + document_id + similarity",
          all({"chunk_id", "document_id", "similarity"} <= s.keys() for s in asst.get("sources") or [{}]),
          str(asst.get("sources")))
    check("top_similarity >= configured threshold",
          (asst.get("top_similarity") or 0) >= settings.RAG_CONFIDENCE_THRESHOLD,
          f'{asst.get("top_similarity")} vs {settings.RAG_CONFIDENCE_THRESHOLD}')
    answer_msg_id = asst.get("id")

    # MessageSource rows actually persisted
    engine = create_engine(settings.DATABASE_URL)
    with engine.connect() as c:
        n = c.execute(text("select count(*) from message_sources where message_id = :m"), {"m": answer_msg_id}).scalar()
    check("MessageSource rows written to DB", n == len(asst.get("sources") or []), f"{n} rows")

    # --- 2. out-of-KB question -> refusal / handoff ---
    r2 = requests.post(
        f"{BASE}/conversations/{conv_id}/messages/text",
        headers=auth(t_a),
        json={"text": "What is the airspeed velocity of an unladen swallow?"},
        timeout=120,
    )
    a2 = r2.json().get("assistant_message", {}) if r2.status_code == 201 else {}
    check("out-of-KB answered=False", a2.get("answered") is False, str(a2))
    check("out-of-KB reason=low_confidence/no_documents",
          a2.get("reason") in ("low_confidence", "no_documents"), str(a2.get("reason")))
    check("out-of-KB has no sources", (a2.get("sources") or []) == [], str(a2.get("sources")))
    check("out-of-KB returns handoff text", "support representative" in (a2.get("raw_text") or "").lower(), str(a2.get("raw_text")))

    # --- 3. language propagation (Roman Urdu in -> Roman Urdu out) ---
    r3 = requests.post(
        f"{BASE}/conversations/{conv_id}/messages/text",
        headers=auth(t_a),
        json={"text": "Mera internet package activate kyun nahi ho raha?"},
        timeout=120,
    )
    b3 = r3.json() if r3.status_code == 201 else {}
    check("Roman Urdu detected on customer message", b3.get("customer_message", {}).get("language") == "roman-ur", str(b3.get("customer_message")))
    check("assistant reply carries same language", b3.get("assistant_message", {}).get("language") == "roman-ur", str(b3.get("assistant_message")))

    # --- 4. transcript shows both turns ---
    tr = requests.get(f"{BASE}/conversations/{conv_id}", headers=auth(t_a), timeout=30).json()
    roles = [m["role"] for m in tr.get("messages", [])]
    check("transcript has customer + system turns", roles.count("customer") >= 3 and roles.count("system") >= 3, str(roles))

    # --- 5. another org, no documents -> always handoff ---
    conv_b = requests.post(f"{BASE}/conversations", headers=auth(t_b), json={"channel": "text"}, timeout=30).json()
    rb = requests.post(
        f"{BASE}/conversations/{conv_b['id']}/messages/text",
        headers=auth(t_b),
        json={"text": "How do I check my account balance?"},
        timeout=120,
    )
    ab = rb.json().get("assistant_message", {}) if rb.status_code == 201 else {}
    check("org B (no docs) answered=False", ab.get("answered") is False, str(ab))
    check("org B reason=no_documents", ab.get("reason") == "no_documents", str(ab.get("reason")))

    # --- 6. auth ---
    na = requests.post(f"{BASE}/conversations/{conv_id}/messages/text", json={"text": "hi"}, timeout=30)
    check("no token -> 401", na.status_code == 401, str(na.status_code))

    print(f"\n{'=' * 50}\nPASSED: {len(PASSED)}   FAILED: {len(FAILED)}")
    if FAILED:
        print("FAILED:", ", ".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
