# Evaluation harness (Phase 10)

```bash
cd backend
LLM_PROVIDER=mock .venv/Scripts/python eval/run_eval.py     # language + refusal + retrieval
LLM_PROVIDER=google .venv/Scripts/python eval/run_eval.py   # + intent, + real generated answers
```

Runs `dataset.py` (15 labelled questions — English / Urdu / Roman Urdu, in-KB and
out-of-KB) through the API with a `TestClient` (no server needed), against the KB
in `knowledge.txt`. Writes `report.json` and prints a summary.

## Metrics

| metric | needs LLM | what it measures |
|---|---|---|
| `language` | no | detected language == label |
| `refusal` | no | the system answers **iff** the answer is in the KB (the "no hallucinated answers" guarantee — decided from retrieval confidence, before any LLM call) |
| `retrieval` | no | in-KB questions clear `RAG_CONFIDENCE_THRESHOLD` |
| `intent` | yes | classified intent == label (skipped under `LLM_PROVIDER=mock`) |

`run_eval.py` exits non-zero if a metric drops below its regression floor
(`language` 0.90, `refusal` 0.80, `retrieval` 0.85).

## Baseline (2026-09-06, `LLM_PROVIDER=mock`)

```
language    15/15  (100%)
refusal     13/15  (87%)
retrieval   14/15  (93%)
```

The two `refusal` / `retrieval` misses are known and documented, not bugs to
paper over:

1. **Urdu-script "how do I check my balance"** retrieves the English KB passage at
   ~0.77 — just under the 0.78 threshold — so it hands off instead of answering.
   Cross-lingual (Urdu query → English passage) retrieval with `multilingual-e5`
   sits right at the margin. Mitigations: a slightly lower threshold, or storing
   an Urdu paraphrase of each chunk.
2. **"international roaming"** (not in the KB) scores ~0.81 against an unrelated
   passage because `multilingual-e5` similarity rarely drops below ~0.75 even for
   unrelated text. A reranker or a small margin check would separate these.

Phase 8's `GAP_SIMILARITY_THRESHOLD` exists for the same reason.
