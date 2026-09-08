"""
Pipeline benchmark (Phase 10).

Times each stage of the request pipeline and the end-to-end text-message
roundtrip. Sub-stages call the services directly; the roundtrip uses a
TestClient. Run with LLM_PROVIDER=mock / TTS_PROVIDER=mock to isolate our own
latency from the model providers'.

    cd backend
    LLM_PROVIDER=mock TTS_PROVIDER=mock .venv/Scripts/python scripts/benchmark.py
"""
from __future__ import annotations

import statistics
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from starlette.testclient import TestClient

QUERIES = [
    "How do I check my account balance?",
    "Mera internet package activate kyun nahi ho raha?",
    "How do I port my number to ACME?",
    "aap ka customer support kab tak available hai?",
]


def bench(name: str, fn, rounds: int) -> None:
    # one warm-up (model load, connection pool, JIT)
    fn(0)
    samples = []
    for i in range(rounds):
        t = time.perf_counter()
        fn(i)
        samples.append((time.perf_counter() - t) * 1000)
    samples.sort()
    p = lambda q: samples[min(len(samples) - 1, int(q * len(samples)))]
    print(f"  {name:28s}  n={rounds:3d}  min {samples[0]:7.1f}  p50 {p(0.5):7.1f}  "
          f"p95 {p(0.95):7.1f}  max {samples[-1]:7.1f}   (ms)")


def main() -> int:
    from app.services.speech.language_utils import detect_language, normalize_text
    from app.services.rag.embeddings import embed_query
    from app.services.nlu.intent import classify_message
    from app.services.tts.synthesis import synthesize_reply
    from app.models.conversation_message import DetectedLanguage

    print("Sub-stages (direct calls):")
    bench("language detection", lambda i: detect_language(QUERIES[i % len(QUERIES)]), 500)
    bench("normalize text", lambda i: normalize_text(QUERIES[i % len(QUERIES)], DetectedLanguage.english), 500)
    bench("embed query (e5-large, CPU)", lambda i: embed_query(QUERIES[i % len(QUERIES)]), 30)
    bench("intent classify (mock LLM)", lambda i: classify_message(QUERIES[i % len(QUERIES)], DetectedLanguage.english), 20)
    bench("tts synthesize (mock)", lambda i: synthesize_reply("Your balance is 500 rupees.", DetectedLanguage.english), 20)

    print("\nEnd-to-end (TestClient, real DB):")
    from app.main import app
    client = TestClient(app)
    org = client.post("/api/v1/organizations", json={"name": f"bench-{uuid.uuid4().hex[:8]}"}).json()
    email = f"bench-{uuid.uuid4().hex[:8]}@x.com"
    client.post("/api/v1/auth/register", json={
        "organization_id": org["id"], "full_name": "b", "email": email, "password": "BenchPass123!", "role": "admin"})
    tok = client.post("/api/v1/auth/login", data={"username": email, "password": "BenchPass123!"}).json()["access_token"]
    H = {"Authorization": f"Bearer {tok}"}
    with open(Path(__file__).resolve().parents[1] / "eval" / "knowledge.txt", "rb") as f:
        client.post("/api/v1/knowledge/documents", headers=H, files={"file": ("kb.txt", f, "text/plain")})
    conv = client.post("/api/v1/conversations", headers=H, json={"channel": "text"}).json()["id"]

    def roundtrip(i: int) -> None:
        r = client.post(f"/api/v1/conversations/{conv}/messages/text", headers=H,
                        json={"text": QUERIES[i % len(QUERIES)]})
        r.raise_for_status()

    bench("POST /messages/text", roundtrip, 25)

    print("\nNote: with a real LLM/TTS provider add ~0.5-3 s per call for Gemini,")
    print("      and ~5 s for the first embed (model load) — see eval/report.json for quality.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
