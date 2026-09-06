"""
Phase 6 verification — text-to-speech voice responses.

Runs with TTS_PROVIDER=mock (silent WAV) so the pipeline is deterministic:
    LLM_PROVIDER=mock TTS_PROVIDER=mock .venv/Scripts/uvicorn app.main:app --port 8001
    VIP_BASE_URL=http://127.0.0.1:8001 .venv/Scripts/python scripts/verify_phase6.py

Checks: /messages/text/spoken attaches an audio_url; GET on it returns a valid
WAV; a plain /messages/text reply has no audio_url but audio can still be
synthesized on demand; the transcript exposes audio_url; a customer text message
has no audio (404); no token -> 401.
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


def is_wav(body: bytes) -> bool:
    return len(body) > 44 and body[:4] == b"RIFF" and body[8:12] == b"WAVE"


FAQ = "ACME FAQ\n\nHow do I check my account balance?\nDial *123# or open the ACME app and tap Balance.\n"


def main() -> int:
    s = uuid.uuid4().hex[:8]
    org = requests.post(f"{BASE}/organizations", json={"name": f"p6-{s}"}, timeout=30).json()
    email = f"p6-{s}@x.com"
    requests.post(f"{BASE}/auth/register", json={
        "organization_id": org["id"], "full_name": "a", "email": email, "password": "Pass123!", "role": "admin"
    }, timeout=30).raise_for_status()
    tok = requests.post(f"{BASE}/auth/login", data={"username": email, "password": "Pass123!"}, timeout=30).json()["access_token"]
    H = {"Authorization": f"Bearer {tok}"}

    requests.post(f"{BASE}/knowledge/documents", headers=H,
                  files={"file": ("faq.txt", io.BytesIO(FAQ.encode()), "text/plain")}, timeout=600)
    conv = requests.post(f"{BASE}/conversations", headers=H, json={"channel": "voice"}, timeout=30).json()["id"]

    # 1. spoken reply
    r = requests.post(f"{BASE}/conversations/{conv}/messages/text/spoken", headers=H,
                      json={"text": "How do I check my balance?"}, timeout=180)
    check("POST /messages/text/spoken -> 201", r.status_code == 201, r.text)
    asst = r.json().get("assistant_message", {})
    audio_url = asst.get("audio_url")
    check("spoken assistant_message has audio_url", bool(audio_url), str(asst))

    if audio_url:
        a = requests.get(f"{ROOT}{audio_url}", headers=H, timeout=60)
        check("GET audio_url -> 200", a.status_code == 200, str(a.status_code))
        check("audio is audio/wav", a.headers.get("content-type", "").startswith("audio/"), a.headers.get("content-type", ""))
        check("audio body is a valid WAV", is_wav(a.content), f"{len(a.content)} bytes, head={a.content[:12]!r}")

    # 2. plain text reply — no audio_url, but synthesizable on demand
    r2 = requests.post(f"{BASE}/conversations/{conv}/messages/text", headers=H,
                       json={"text": "How do I check my balance?"}, timeout=180)
    asst2 = r2.json()["assistant_message"]
    check("plain /messages/text reply has no audio_url", asst2.get("audio_url") is None, str(asst2.get("audio_url")))
    lazy = requests.get(f"{BASE}/conversations/{conv}/messages/{asst2['id']}/audio", headers=H, timeout=60)
    check("audio synthesized on demand for a plain reply -> 200 WAV", lazy.status_code == 200 and is_wav(lazy.content), str(lazy.status_code))

    # 3. transcript exposes audio_url on the spoken assistant message
    tr = requests.get(f"{BASE}/conversations/{conv}", headers=H, timeout=30).json()
    sys_with_audio = [m for m in tr["messages"] if m["role"] == "system" and m.get("audio_url")]
    check("transcript shows audio_url on assistant messages", len(sys_with_audio) >= 1, str([m.get("audio_url") for m in tr["messages"]]))

    # 4. customer text message has no audio
    cust = next(m for m in tr["messages"] if m["role"] == "customer")
    nc = requests.get(f"{BASE}/conversations/{conv}/messages/{cust['id']}/audio", headers=H, timeout=30)
    check("customer text message audio -> 404", nc.status_code == 404, str(nc.status_code))

    # 5. auth
    na = requests.get(f"{BASE}/conversations/{conv}/messages/{asst2['id']}/audio", timeout=30)
    check("audio without token -> 401", na.status_code == 401, str(na.status_code))

    print(f"\n{'=' * 50}\nPASSED: {len(PASSED)}   FAILED: {len(FAILED)}")
    if FAILED:
        print("FAILED:", "; ".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
