"""
Phase 8 verification — question clustering + knowledge-gap detection + learning loop.

Clustering and gap detection use the real embedding model, so this is a genuine
test even with LLM_PROVIDER=mock (only answer generation is mocked):
    LLM_PROVIDER=mock TTS_PROVIDER=mock .venv/Scripts/uvicorn app.main:app --port 8001
    VIP_BASE_URL=http://127.0.0.1:8001 .venv/Scripts/python scripts/verify_phase8.py

Seeds a KB that covers balance checking but NOT international roaming, sends
paraphrased questions on both topics, then checks: recluster groups them, the
roaming cluster is flagged as a gap and the balance one isn't, an admin resolves
the gap with a curated answer that immediately becomes retrievable, and RBAC /
tenant isolation hold.
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


KB = (
    "ACME Telecom FAQ\n\n"
    "How do I check my account balance?\n"
    "Dial *123# from your ACME SIM, or open the ACME app and tap Balance. Your "
    "remaining balance and expiry date are shown there.\n"
)

BALANCE_QS = [
    "How do I check my account balance?",
    "How can I see my remaining balance?",
    "Where do I view how much balance I have left?",
]
ROAMING_QS = [
    "How do I activate international roaming before I travel?",
    "I am going abroad next week, how do I turn on international roaming?",
    "What do I need to do to enable roaming for another country?",
]


def send(headers: dict, conv_id: str, text: str) -> None:
    requests.post(f"{BASE}/conversations/{conv_id}/messages/text", headers=headers,
                  json={"text": text}, timeout=120).raise_for_status()


def main() -> int:
    s = uuid.uuid4().hex[:8]
    org_a = requests.post(f"{BASE}/organizations", json={"name": f"p8a-{s}"}, timeout=30).json()
    org_b = requests.post(f"{BASE}/organizations", json={"name": f"p8b-{s}"}, timeout=30).json()
    Ha = reg(org_a["id"], f"ad-{s}@a.com", "admin")
    Hg = reg(org_a["id"], f"ag-{s}@a.com", "agent")
    Hu = reg(org_a["id"], f"us-{s}@a.com", "user")
    Hb = reg(org_b["id"], f"ad-{s}@b.com", "admin")

    requests.post(f"{BASE}/knowledge/documents", headers=Ha,
                  files={"file": ("faq.txt", io.BytesIO(KB.encode()), "text/plain")}, timeout=600)
    conv = requests.post(f"{BASE}/conversations", headers=Ha, json={"channel": "text"}, timeout=30).json()["id"]
    for q in BALANCE_QS + ROAMING_QS + ["What are your office opening hours?"]:
        send(Ha, conv, q)

    # RBAC on recluster
    check("recluster (role=user) -> 403", requests.post(f"{BASE}/learning/recluster", headers=Hu, timeout=120).status_code == 403)

    run = requests.post(f"{BASE}/learning/recluster", headers=Hg, timeout=180)
    check("recluster -> 200", run.status_code == 200, run.text)
    stats = run.json() if run.status_code == 200 else {}
    check("processed all 7 questions", stats.get("messages_processed") == 7, str(stats))
    check("created >= 2 clusters", (stats.get("clusters_created") or 0) >= 2, str(stats))
    check("found >= 1 knowledge gap", (stats.get("open_gaps") or 0) >= 1, str(stats))

    clusters = requests.get(f"{BASE}/learning/clusters", headers=Hg, timeout=30).json()
    gaps = requests.get(f"{BASE}/learning/gaps", headers=Hg, timeout=30).json()
    check("at least one covered cluster is NOT a gap",
          any((not c["is_gap"]) and c["member_count"] >= 2 for c in clusters), str(clusters))
    check("at least one gap cluster with >= 2 members", any(c["member_count"] >= 2 for c in gaps), str(gaps))

    roaming = next((c for c in gaps if c["member_count"] >= 2), None)
    if roaming is None:
        check("found the roaming gap cluster", False, str(gaps))
        return _summary()
    check("gap cluster top_kb_similarity below threshold", roaming["top_kb_similarity"] < 0.78, str(roaming["top_kb_similarity"]))

    detail = requests.get(f"{BASE}/learning/clusters/{roaming['id']}", headers=Hg, timeout=30).json()
    check("gap cluster lists its member questions", len(detail.get("members", [])) >= 2, str(detail.get("members")))

    # resolve is admin-only
    check("resolve (agent) -> 403",
          requests.post(f"{BASE}/learning/clusters/{roaming['id']}/resolve", headers=Hg,
                        json={"title": "x", "answer_text": "x"}, timeout=60).status_code == 403)

    res = requests.post(f"{BASE}/learning/clusters/{roaming['id']}/resolve", headers=Ha, json={
        "title": "International roaming activation",
        "answer_text": "To activate international roaming, dial *111*6# before you travel, or "
                       "enable Roaming in the ACME app under Settings. Roaming charges apply per the "
                       "destination country's rate sheet.",
    }, timeout=180)
    check("resolve -> 200", res.status_code == 200, res.text)
    body = res.json() if res.status_code == 200 else {}
    check("cluster now addressed", body.get("status") == "addressed", str(body.get("status")))
    check("cluster no longer a gap", body.get("is_gap") is False, str(body.get("is_gap")))
    check("cluster links the curated document", body.get("resolved_document_id") is not None, str(body))

    # the curated answer is retrievable now
    srch = requests.post(f"{BASE}/knowledge/search", headers=Ha,
                         json={"query": "how to enable international roaming", "top_k": 3}, timeout=60).json()
    check("curated answer is retrievable",
          any("roaming" in h["text"].lower() and "*111*6#" in h["text"] for h in srch), str(srch)[:300])

    # a real customer question on that topic is now answered, not refused
    ans = requests.post(f"{BASE}/conversations/{conv}/messages/text", headers=Ha,
                        json={"text": "how do I turn on roaming for my trip abroad?"}, timeout=120).json()["assistant_message"]
    check("roaming question now clears the confidence threshold",
          ans["top_similarity"] >= 0.78, str(ans["top_similarity"]))

    # dismiss another cluster
    other = next((c for c in clusters if c["id"] != roaming["id"]), None)
    if other:
        d = requests.post(f"{BASE}/learning/clusters/{other['id']}/dismiss", headers=Ha, timeout=30)
        check("dismiss -> 200 + status dismissed", d.status_code == 200 and d.json()["status"] == "dismissed", d.text)

    # tenant isolation
    check("org B cannot see org A's cluster -> 404",
          requests.get(f"{BASE}/learning/clusters/{roaming['id']}", headers=Hb, timeout=30).status_code == 404)
    check("recluster without token -> 401", requests.post(f"{BASE}/learning/recluster", timeout=30).status_code == 401)

    return _summary()


def _summary() -> int:
    print(f"\n{'=' * 50}\nPASSED: {len(PASSED)}   FAILED: {len(FAILED)}")
    if FAILED:
        print("FAILED:", "; ".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
