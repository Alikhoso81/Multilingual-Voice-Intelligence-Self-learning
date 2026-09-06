"""
Phase 7 verification — conversation analytics (summary / sentiment / resolution).

Runs with LLM_PROVIDER=mock (the mock returns valid analytics JSON):
    LLM_PROVIDER=mock TTS_PROVIDER=mock .venv/Scripts/uvicorn app.main:app --port 8001
    VIP_BASE_URL=http://127.0.0.1:8001 .venv/Scripts/python scripts/verify_phase7.py

Checks: the staff conversations list (RBAC: not for role=user), status PATCH,
POST /analyze stores summary + sentiment + resolution + analyzed_at and returns
an intent breakdown, and those fields then show on the conversation + list.
"""
from __future__ import annotations

import io
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests

ROOT = os.getenv("VIP_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
BASE = f"{ROOT}/api/v1"
SENTIMENTS = {"positive", "neutral", "negative", "frustrated", "unknown"}
RESOLUTIONS = {"resolved", "unresolved", "needs_follow_up", "escalated", "unknown"}

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASSED if ok else FAILED).append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if detail and not ok else ""))


def reg(org_id: str, email: str, role: str) -> str:
    requests.post(f"{BASE}/auth/register", json={
        "organization_id": org_id, "full_name": email[:4], "email": email, "password": "Pass123!", "role": role
    }, timeout=30).raise_for_status()
    return requests.post(f"{BASE}/auth/login", data={"username": email, "password": "Pass123!"}, timeout=30).json()["access_token"]


def main() -> int:
    s = uuid.uuid4().hex[:8]
    org = requests.post(f"{BASE}/organizations", json={"name": f"p7-{s}"}, timeout=30).json()
    t_admin = reg(org["id"], f"ad-{s}@x.com", "admin")
    t_agent = reg(org["id"], f"ag-{s}@x.com", "agent")
    t_user = reg(org["id"], f"us-{s}@x.com", "user")
    Ha, Hg, Hu = ({"Authorization": f"Bearer {t}"} for t in (t_admin, t_agent, t_user))

    requests.post(f"{BASE}/knowledge/documents", headers=Ha,
                  files={"file": ("faq.txt", io.BytesIO(b"ACME FAQ\n\nHow do I check my balance?\nDial *123#.\n"), "text/plain")}, timeout=600)
    conv_id = requests.post(f"{BASE}/conversations", headers=Ha, json={"channel": "text"}, timeout=30).json()["id"]
    for q in ["How do I check my balance?", "and what about data packages?", "thanks"]:
        requests.post(f"{BASE}/conversations/{conv_id}/messages/text", headers=Ha, json={"text": q}, timeout=120).raise_for_status()

    # list — staff only
    lst = requests.get(f"{BASE}/conversations", headers=Hg, timeout=30)
    check("GET /conversations (agent) -> 200", lst.status_code == 200, lst.text)
    row = next((c for c in lst.json() if c["id"] == conv_id), None)
    check("conversation appears in the list", row is not None, "missing")
    check("message_count == 6", row and row["message_count"] == 6, str(row and row["message_count"]))
    check("not yet analyzed", row and row["analyzed_at"] is None, str(row and row["analyzed_at"]))
    check("GET /conversations (role=user) -> 403", requests.get(f"{BASE}/conversations", headers=Hu, timeout=30).status_code == 403)

    # status patch
    pu = requests.patch(f"{BASE}/conversations/{conv_id}", headers=Hu, json={"status": "resolved"}, timeout=30)
    check("PATCH status (role=user) -> 403", pu.status_code == 403, str(pu.status_code))
    pa = requests.patch(f"{BASE}/conversations/{conv_id}", headers=Hg, json={"status": "escalated"}, timeout=30)
    check("PATCH status (agent) -> 200 + applied", pa.status_code == 200 and pa.json()["status"] == "escalated", pa.text)

    # analyze
    an = requests.post(f"{BASE}/conversations/{conv_id}/analyze", headers=Hg, timeout=180)
    check("POST /analyze -> 200", an.status_code == 200, an.text)
    body = an.json() if an.status_code == 200 else {}
    check("analyzed == True", body.get("analyzed") is True, str(body))
    check("summary is non-empty", bool((body.get("summary") or "").strip()), str(body.get("summary")))
    check("sentiment in enum", body.get("sentiment") in SENTIMENTS, str(body.get("sentiment")))
    check("resolution in enum", body.get("resolution") in RESOLUTIONS, str(body.get("resolution")))
    check("intent_breakdown is a non-empty dict", isinstance(body.get("intent_breakdown"), dict) and body["intent_breakdown"], str(body.get("intent_breakdown")))

    # persisted on the conversation
    got = requests.get(f"{BASE}/conversations/{conv_id}", headers=Hg, timeout=30).json()
    check("conversation.summary persisted", bool(got.get("summary")), str(got.get("summary")))
    check("conversation.sentiment persisted", got.get("sentiment") in SENTIMENTS, str(got.get("sentiment")))
    check("conversation.analyzed_at persisted", got.get("analyzed_at") is not None, str(got.get("analyzed_at")))

    lst2 = requests.get(f"{BASE}/conversations", headers=Hg, timeout=30).json()
    row2 = next(c for c in lst2 if c["id"] == conv_id)
    check("list row now shows analyzed_at + summary", row2["analyzed_at"] is not None and bool(row2["summary"]), str(row2))

    # errors
    check("analyze missing conversation -> 404",
          requests.post(f"{BASE}/conversations/{uuid.uuid4()}/analyze", headers=Hg, timeout=30).status_code == 404)
    check("analyze without token -> 401",
          requests.post(f"{BASE}/conversations/{conv_id}/analyze", timeout=30).status_code == 401)

    print(f"\n{'=' * 50}\nPASSED: {len(PASSED)}   FAILED: {len(FAILED)}")
    if FAILED:
        print("FAILED:", "; ".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
