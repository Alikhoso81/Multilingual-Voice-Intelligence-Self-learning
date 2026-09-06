"""
Phase 5 verification — intent classification + entity extraction.

Needs a real LLM provider (classification is an LLM call): run the server with
GOOGLE_API_KEY set, then:
    VIP_BASE_URL=http://127.0.0.1:8001 .venv/Scripts/python scripts/verify_phase5.py

Assertions on `intent` accept a small set of plausible labels per message, since
the classifier is generative and a little variable — the point is that it lands
in the right neighbourhood, extracts the obvious entities, and never blocks the
conversation.
"""
from __future__ import annotations

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
ENTITY_KEYS = {
    "phone_numbers", "amounts", "package_or_product_names",
    "dates_or_times", "account_or_order_ids", "locations",
}


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASSED if ok else FAILED).append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if detail and not ok else ""))


def send(token: str, conv_id: str, text: str) -> dict:
    r = requests.post(
        f"{BASE}/conversations/{conv_id}/messages/text",
        headers={"Authorization": f"Bearer {token}"},
        json={"text": text},
        timeout=180,
    )
    r.raise_for_status()
    return r.json()["customer_message"]


def main() -> int:
    s = uuid.uuid4().hex[:8]
    org = requests.post(f"{BASE}/organizations", json={"name": f"p5-{s}", "industry": "telecom"}, timeout=30).json()
    email = f"p5-{s}@x.com"
    requests.post(f"{BASE}/auth/register", json={
        "organization_id": org["id"], "full_name": "a", "email": email, "password": "Pass123!", "role": "admin"
    }, timeout=30).raise_for_status()
    token = requests.post(f"{BASE}/auth/login", data={"username": email, "password": "Pass123!"}, timeout=30).json()["access_token"]
    conv_id = requests.post(f"{BASE}/conversations", headers={"Authorization": f"Bearer {token}"},
                            json={"channel": "text"}, timeout=30).json()["id"]

    cases = [
        ("Why is my bill so high this month? I was charged 5000 rupees extra.",
         {"billing", "complaint"}, "amounts"),
        ("My internet has not been working since this morning.",
         {"technical_support"}, None),
        ("I want to cancel the SIM for number 03001234567.",
         {"account_management"}, "phone_numbers"),
        ("What data packages do you offer for students?",
         {"sales_inquiry", "general_inquiry"}, None),
        ("aap ka customer care office kitne baje tak khula rehta hai?",
         {"general_inquiry"}, None),
    ]

    for text, plausible, want_entity in cases:
        m = send(token, conv_id, text)
        label = text[:45] + "..."
        check(f"[{label}] intent in {plausible}", m.get("intent") in plausible,
              f'got {m.get("intent")!r}')
        conf = m.get("intent_confidence")
        check(f"[{label}] confidence in (0,1]", isinstance(conf, (int, float)) and 0.0 < conf <= 1.0, str(conf))
        ents = m.get("entities") or {}
        check(f"[{label}] entities has the 6 category keys", set(ents.keys()) == ENTITY_KEYS, str(list(ents.keys())))
        if want_entity == "phone_numbers":
            check(f"[{label}] extracted the phone number",
                  any("3001234567" in p.replace(" ", "").replace("-", "") for p in ents.get("phone_numbers", [])),
                  str(ents.get("phone_numbers")))
        if want_entity == "amounts":
            check(f"[{label}] extracted the amount",
                  any("5000" in a for a in ents.get("amounts", [])), str(ents.get("amounts")))

    # language still detected on a Roman Urdu message
    m_ur = send(token, conv_id, "mera balance kyun kat gaya hai, yeh galat hai")
    check("Roman Urdu message classified (intent not unknown)", m_ur.get("intent") != "unknown", str(m_ur.get("intent")))

    # transcript: customer messages carry intent, system messages don't
    tr = requests.get(f"{BASE}/conversations/{conv_id}", headers={"Authorization": f"Bearer {token}"}, timeout=30).json()
    cust = [m for m in tr["messages"] if m["role"] == "customer"]
    syst = [m for m in tr["messages"] if m["role"] == "system"]
    check("all customer messages have an intent", all(m.get("intent") for m in cust), "some missing")
    check("system messages have no intent", all(m.get("intent") is None for m in syst), "some set")

    print(f"\n{'=' * 50}\nPASSED: {len(PASSED)}   FAILED: {len(FAILED)}")
    if FAILED:
        print("FAILED:", "; ".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
