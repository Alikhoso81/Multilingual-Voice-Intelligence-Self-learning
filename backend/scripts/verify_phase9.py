"""
Phase 9 verification — dashboard aggregates + the static dashboard page.

    LLM_PROVIDER=mock TTS_PROVIDER=mock .venv/Scripts/uvicorn app.main:app --port 8001
    VIP_BASE_URL=http://127.0.0.1:8001 .venv/Scripts/python scripts/verify_phase9.py
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

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASSED if ok else FAILED).append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if detail and not ok else ""))


def reg(org_id: str, email: str, role: str) -> dict:
    requests.post(f"{BASE}/auth/register", json={
        "organization_id": org_id, "full_name": email[:4], "email": email, "password": "Pass123!", "role": role
    }, timeout=30).raise_for_status()
    tok = requests.post(f"{BASE}/auth/login", data={"username": email, "password": "Pass123!"}, timeout=30).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def main() -> int:
    s = uuid.uuid4().hex[:8]
    org = requests.post(f"{BASE}/organizations", json={"name": f"p9-{s}"}, timeout=30).json()
    Ha = reg(org["id"], f"ad-{s}@x.com", "admin")
    Hg = reg(org["id"], f"ag-{s}@x.com", "agent")
    Hu = reg(org["id"], f"us-{s}@x.com", "user")

    requests.post(f"{BASE}/knowledge/documents", headers=Ha,
                  files={"file": ("faq.txt", io.BytesIO(b"ACME FAQ\n\nHow do I check my balance?\nDial *123#.\n"), "text/plain")}, timeout=600)
    conv = requests.post(f"{BASE}/conversations", headers=Ha, json={"channel": "text"}, timeout=30).json()["id"]
    for q in ["How do I check my balance?", "How do I check my balance again?",
              "How do I activate international roaming abroad?", "office hours?"]:
        requests.post(f"{BASE}/conversations/{conv}/messages/text", headers=Ha, json={"text": q}, timeout=120).raise_for_status()
    requests.post(f"{BASE}/conversations/{conv}/analyze", headers=Ha, timeout=120)
    requests.post(f"{BASE}/learning/recluster", headers=Ha, timeout=180)

    # RBAC
    check("overview (role=user) -> 403", requests.get(f"{BASE}/dashboard/overview", headers=Hu, timeout=30).status_code == 403)
    check("overview (no token) -> 401", requests.get(f"{BASE}/dashboard/overview", timeout=30).status_code == 401)

    ov = requests.get(f"{BASE}/dashboard/overview", headers=Hg, timeout=30)
    check("overview (agent) -> 200", ov.status_code == 200, ov.text)
    d = ov.json() if ov.status_code == 200 else {}
    check("total_conversations >= 1", d.get("total_conversations", 0) >= 1, str(d.get("total_conversations")))
    check("customer_messages == 4", d.get("customer_messages") == 4, str(d.get("customer_messages")))
    check("assistant_messages == 4", d.get("assistant_messages") == 4, str(d.get("assistant_messages")))
    check("answered + deflected == assistant_messages",
          d.get("answered_replies", 0) + d.get("deflected_replies", 0) == d.get("assistant_messages"),
          f'{d.get("answered_replies")}+{d.get("deflected_replies")} vs {d.get("assistant_messages")}')
    check("deflection_rate is 0..1", isinstance(d.get("deflection_rate"), (int, float)) and 0 <= d["deflection_rate"] <= 1, str(d.get("deflection_rate")))
    check("intent_breakdown non-empty", bool(d.get("intent_breakdown")), str(d.get("intent_breakdown")))
    check("language_breakdown non-empty", bool(d.get("language_breakdown")), str(d.get("language_breakdown")))
    check("analyzed_conversations >= 1", d.get("analyzed_conversations", 0) >= 1, str(d.get("analyzed_conversations")))
    check("knowledge_documents >= 1 and chunks > 0", d.get("knowledge_documents", 0) >= 1 and d.get("knowledge_chunks", 0) > 0, str(d))
    check("clusters_total >= 1", d.get("clusters_total", 0) >= 1, str(d.get("clusters_total")))
    check("open_gaps >= 1", d.get("open_gaps", 0) >= 1, str(d.get("open_gaps")))

    # static dashboard page
    page = requests.get(f"{ROOT}/app/", timeout=30)
    check("GET /app/ -> 200 html", page.status_code == 200 and "text/html" in page.headers.get("content-type", ""), str(page.status_code))
    check("dashboard page has the app shell", "Voice Intelligence" in page.text and 'id="app"' in page.text, "markers missing")

    print(f"\n{'=' * 50}\nPASSED: {len(PASSED)}   FAILED: {len(FAILED)}")
    if FAILED:
        print("FAILED:", "; ".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
