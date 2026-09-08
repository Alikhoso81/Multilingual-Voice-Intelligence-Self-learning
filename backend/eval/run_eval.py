"""
Evaluation harness (Phase 10).

Runs the labelled set in dataset.py through the live API (FastAPI TestClient, no
server needed), scoring four dimensions:

  language     — DetectedLanguage matches the label
  refusal      — the system answers iff the answer is in the KB (the "no
                 hallucinated answers" guarantee — measured without the LLM,
                 from retrieval confidence)
  retrieval    — for in-KB questions, at least one chunk clears the threshold
  intent       — MessageIntent matches the label (graded only with a real LLM
                 provider; skipped under LLM_PROVIDER=mock)

Usage (from backend/):
    .venv/Scripts/python eval/run_eval.py
Writes eval/report.json and prints a summary.

Set GOOGLE_API_KEY + LLM_PROVIDER=google to also grade intent and see real
generated answers.
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from starlette.testclient import TestClient

from app.core.config import settings
from app.main import app
from eval.dataset import CASES

HERE = Path(__file__).resolve().parent


def _bearer(client: TestClient, org_id: str, email: str) -> dict:
    client.post("/api/v1/auth/register", json={
        "organization_id": org_id, "full_name": "eval", "email": email,
        "password": "EvalPass123!", "role": "admin",
    }).raise_for_status()
    tok = client.post("/api/v1/auth/login", data={"username": email, "password": "EvalPass123!"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def main() -> int:
    grade_intent = settings.LLM_PROVIDER.lower() != "mock"
    client = TestClient(app)

    org = client.post("/api/v1/organizations", json={"name": f"eval-{uuid.uuid4().hex[:8]}"}).json()
    H = _bearer(client, org["id"], f"eval-{uuid.uuid4().hex[:8]}@x.com")

    with open(HERE / "knowledge.txt", "rb") as f:
        up = client.post("/api/v1/knowledge/documents", headers=H, files={"file": ("kb.txt", f, "text/plain")})
    assert up.json().get("status") == "ready", up.text

    conv = client.post("/api/v1/conversations", headers=H, json={"channel": "text"}).json()["id"]

    totals = {"language": [0, 0], "refusal": [0, 0], "retrieval": [0, 0], "intent": [0, 0]}
    rows = []

    for case in CASES:
        r = client.post(f"/api/v1/conversations/{conv}/messages/text", headers=H, json={"text": case.question})
        r.raise_for_status()
        body = r.json()
        cust, asst = body["customer_message"], body["assistant_message"]

        lang_ok = cust["language"] == case.language
        answered = asst["answered"]
        refusal_ok = answered == case.in_kb
        retrieval_ok = (asst["top_similarity"] >= settings.RAG_CONFIDENCE_THRESHOLD) if case.in_kb else True
        intent_ok = (cust["intent"] == case.intent) if grade_intent else None

        totals["language"][0] += lang_ok; totals["language"][1] += 1
        totals["refusal"][0] += refusal_ok; totals["refusal"][1] += 1
        totals["retrieval"][0] += retrieval_ok; totals["retrieval"][1] += 1
        if intent_ok is not None:
            totals["intent"][0] += intent_ok; totals["intent"][1] += 1

        rows.append({
            "question": case.question,
            "expected": {"language": case.language, "in_kb": case.in_kb, "intent": case.intent},
            "got": {"language": cust["language"], "answered": answered,
                    "top_similarity": round(asst["top_similarity"], 3), "intent": cust["intent"],
                    "reason": asst["reason"]},
            "pass": {"language": lang_ok, "refusal": refusal_ok, "retrieval": retrieval_ok,
                     "intent": intent_ok},
        })

    scores = {k: round(c / n, 3) if n else None for k, (c, n) in totals.items()}
    report = {
        "provider": settings.LLM_PROVIDER,
        "model": settings.GEMINI_MODEL if settings.LLM_PROVIDER == "google" else settings.ANTHROPIC_MODEL,
        "rag_confidence_threshold": settings.RAG_CONFIDENCE_THRESHOLD,
        "n_cases": len(CASES),
        "scores": scores,
        "cases": rows,
    }
    (HERE / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\nEvaluation — {len(CASES)} cases, provider={settings.LLM_PROVIDER}")
    print("-" * 44)
    for k, (c, n) in totals.items():
        if n == 0:
            print(f"  {k:10s}  skipped (needs a real LLM provider)")
        else:
            print(f"  {k:10s}  {c}/{n}  ({c / n:.0%})")
    print("-" * 44)
    print(f"report: {HERE / 'report.json'}")

    # Regression floors (see eval/README.md for the current baseline and the two
    # known-hard cases — cross-lingual retrieval and e5's similarity floor).
    floors = {"language": 0.90, "refusal": 0.80, "retrieval": 0.85}
    regressions = [k for k, f in floors.items() if scores.get(k) is not None and scores[k] < f]
    if regressions:
        print(f"\nREGRESSION below floor: {', '.join(regressions)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
