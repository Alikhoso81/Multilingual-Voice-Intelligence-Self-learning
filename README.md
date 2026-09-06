# Multilingual Voice Intelligence & Self-Learning Knowledge Platform

Enterprise customer-support AI that takes voice/text in **English, Urdu, Roman Urdu and
mixed Urdu-English**, transcribes and language-detects it, answers from company documents
via RAG (grounded, no hallucinations), detects knowledge gaps, and lets admins approve new
knowledge before it becomes retrievable.

**Stack:** Python + FastAPI · PostgreSQL + pgvector · Faster-Whisper (ASR) ·
`multilingual-e5-large` embeddings · pluggable LLM (Gemini / Claude) · Redis + Celery · Docker.

## Phase status

| Phase | Scope | Status |
|---|---|---|
| 1 | Backend + DB + auth skeleton | ✅ done |
| 2 | Voice→text + language detection/normalization | ✅ code done (voice upload not yet user-tested) |
| 3 | Document ingestion + pgvector + RAG retrieval | ✅ verified end-to-end (Neon + real embeddings) |
| 4 | LLM grounded answer generation + refusal behavior | ✅ verified end-to-end (Gemini + Neon, all 3 languages) |
| 5 | Intent classification + entity extraction | ✅ verified end-to-end (Gemini) |
| 6 | TTS voice response | ✅ verified (mock 10/10; real Gemini TTS confirmed) |
| 7 | Conversation analytics (summary/sentiment/resolution) | ✅ verified (mock 19/19) |
| 8 | Question clustering + knowledge-gap detection + learning center | ✅ verified (real embeddings, 19/19) |
| 9 | Full admin + agent dashboards | ⬜ next |
| 10 | Security hardening, evaluation harness, deployment, benchmarking | ⬜ |

## Run it

Two supported ways. **Local + hosted Postgres** is the current dev setup (no local
database or Docker needed); **Docker** brings everything up in containers.

### Option A — local backend + Neon (hosted Postgres + pgvector)

```bash
cd backend
cp .env.example .env
#   edit .env:
#   - DATABASE_URL = your Neon connection string, with the driver prefixed:
#       postgresql+psycopg2://<user>:<pass>@<host>.neon.tech/neondb?sslmode=require
#   - SECRET_KEY   = python -c "import secrets; print(secrets.token_urlsafe(48))"

uv venv --python 3.11 .venv          # uv installs Python 3.11 if needed
uv pip install --python .venv -r requirements.txt

.venv/Scripts/alembic upgrade head   # create the schema on Neon (Linux/mac: .venv/bin/alembic)
.venv/Scripts/uvicorn app.main:app --reload --port 8000
```

Free Neon project: https://neon.tech → new project → copy the connection string.
`pgvector` is available there; the migration runs `CREATE EXTENSION vector` itself.

### Option B — Docker

```bash
cd backend && cp .env.example .env      # set SECRET_KEY; DATABASE_URL is overridden by compose
cd ../infra && docker compose up --build
docker exec -it vip_backend bash -c "alembic upgrade head"
```

If an **older** migration already created the dev database and `alembic upgrade head`
complains about a missing revision (or a leftover ENUM type), reset the volume —
dev data is disposable: `docker compose down -v && docker compose up --build`.

Backend: http://localhost:8000 · Interactive API docs: http://localhost:8000/docs

## Try it

1. `POST /api/v1/organizations` — create an org, note the returned `id`.
2. `POST /api/v1/auth/register` — create a user with `role: "admin"` under that org.
3. `POST /api/v1/auth/login` — form-encoded `username`/`password`, get back tokens.
4. `GET /api/v1/users/me` with `Authorization: Bearer <access_token>`.
5. `GET /api/v1/users` — only works if your user's role is `admin` (RBAC test).

## What's in Phase 1

- Modular `app/` structure (`core`, `db`, `models`, `schemas`, `api/v1`, `services`, `workers` —
  the last two are empty scaffolding for Phase 2+).
- JWT auth (access + refresh tokens), bcrypt password hashing.
- RBAC dependency (`require_roles`) enforced at the API layer, ready to reuse on every future route.
- `Organization`, `User`, `Customer` models — the multi-tenant foundation everything else attaches to.
- Alembic migrations wired to the models (autogenerate-ready).
- pgvector-enabled Postgres image so Phase 3 (RAG) doesn't need a DB migration to add vector support.
- docker-compose bringing up db + redis + backend together.

## What's in Phase 2 — Voice → Text + Language Detection

- `Conversation`, `Message`, `VoiceRecording` models.
- `POST /api/v1/conversations` — start a conversation (text or voice channel).
- `POST /api/v1/conversations/{id}/messages/text` — send a typed message; runs language
  detection + normalization even on typed text (useful for testing without audio files).
- `POST /api/v1/conversations/{id}/messages/voice` — upload an audio file (wav/mp3/m4a/ogg);
  transcribes with Faster-Whisper, detects language, normalizes, stores everything.
- `GET /api/v1/conversations/{id}` — view full transcript.
- Language detection distinguishes English / Urdu / Roman Urdu / Mixed — tested against
  the exact example sentences from the project spec, all passing.
- Cross-organization isolation: users can only see conversations in their own organization.

### Try Phase 2 in the browser (`/docs`)

1. `POST /conversations` with `{"channel": "text"}` (needs your Bearer token from Phase 1 login).
2. `POST /conversations/{id}/messages/text` with e.g.
   `{"text": "Mera internet package activate kyun nahi ho raha?"}` — check the response:
   `language` should be `"roman-ur"`.
3. For voice: `POST /conversations/{id}/messages/voice`, upload a short `.wav`/`.mp3` file
   recording yourself speaking English, Urdu, or Roman Urdu.

### Important notes on Phase 2

- **First voice request will be slow.** Faster-Whisper downloads its model (~500MB for the
  default "small" size) the first time it's used inside the container. This can take a few
  minutes depending on your internet. Subsequent requests are fast — the model is cached in a
  Docker volume (`whisper_model_cache`) so it survives container restarts.
- **No GPU needed for testing**, but CPU transcription of longer audio will be slower than
  real-time. For a short test clip (a few seconds) this is fine.
- **I could not test the actual Whisper transcription in my own environment** (no audio file /
  no model download available there) — I verified: the code imports correctly, all routes
  register, and the full text-message pipeline (language detection → normalization → storage →
  retrieval) works end-to-end against real Postgres. **Please test the actual voice upload
  yourself** and paste me any error you hit — I'll fix it immediately, same as the earlier bugs.
- If `WHISPER_MODEL_SIZE=small` is too slow on your machine, add `WHISPER_MODEL_SIZE=tiny` or
  `WHISPER_MODEL_SIZE=base` to your `.env` file (faster, less accurate) — no code change needed.

## Not in Phase 1/2 (coming in later phases)

Intent classification, RAG, clustering, analytics, admin dashboard UI — per the roadmap, these
land in Phases 3–10.

## What's in Phase 3 — Document Ingestion + pgvector + RAG Retrieval

New files:
- `app/models/knowledge.py` — `KnowledgeDocument`, `KnowledgeChunk` (with a real pgvector `Vector(1024)` column)
- `app/services/rag/parsing.py` — extracts text from PDF/DOCX/TXT/CSV
- `app/services/rag/chunking.py` — splits text into retrieval-sized, overlapping chunks
- `app/services/rag/embeddings.py` — multilingual-e5-large embeddings (configurable via `EMBEDDING_MODEL_NAME`)
- `app/services/rag/retrieval.py` — pgvector cosine similarity search
- `app/schemas/knowledge.py`, `app/api/v1/knowledge.py` — upload/list/delete/search endpoints

New endpoints:
- `POST /api/v1/knowledge/documents` (admin only) — upload a PDF/DOCX/TXT/CSV, auto parsed+chunked+embedded
- `GET /api/v1/knowledge/documents` — list your org's documents with chunk counts
- `DELETE /api/v1/knowledge/documents/{id}` (admin only)
- `POST /api/v1/knowledge/search` — test retrieval directly: `{"query": "...", "top_k": 5}`

### Running Phase 3

Start the server (see "Run it" above), then either poke it by hand at
http://localhost:8000/docs, or run the automated check:

```bash
cd backend
.venv/Scripts/uvicorn app.main:app --port 8000        # terminal 1
.venv/Scripts/python scripts/verify_phase3.py         # terminal 2  (VIP_BASE_URL to override host)
```

`scripts/verify_phase3.py` exercises the full matrix: upload → parse → chunk → embed →
store → list → semantic search → delete, plus RBAC (agent gets 403), auth (401 with no
token), input validation (415/400 for a `.png`), cross-tenant isolation (org B can't see
or retrieve org A's documents), and cascade delete (chunks go with the document).

The first upload downloads `multilingual-e5-large` (~2.2 GB) — one time, then cached under
`~/.cache/huggingface`.

### Verification status

- ✅ **Verified end-to-end on 2026-09-06** against real Postgres (Neon) + the real
  `multilingual-e5-large` model — `scripts/verify_phase3.py`, 22/22 checks pass
  (upload → parse → chunk → embed → store → semantic search, plus RBAC, auth,
  validation, cross-tenant isolation, cascade delete).
- The migration explicitly enables the `vector` extension (this was missing from the
  autogenerated file and would have failed on a fresh database).
- Embedding runs *before* the DB write and the connection is released first — a first
  upload triggers a multi-minute model download, long enough that a hosted Postgres
  drops an idle connection and the final commit fails otherwise.

### Setup notes for Phase 3

1. `alembic/script.py.mako` always adds `import pgvector.sqlalchemy` to generated migrations,
   so future vector-column autogenerates don't fail with `NameError: name 'pgvector' is not
   defined`.
2. **First document upload will be slow** — same as Whisper in Phase 2, `multilingual-e5-large`
   (~2.2GB) downloads once on first use and is cached in a Docker volume after that.
3. **If your machine is slow/low on resources**, add to `.env`:
   `EMBEDDING_MODEL_NAME=intfloat/multilingual-e5-small` — but if you do this, you MUST also
   change `EMBEDDING_DIM = 1024` to `384` in `app/models/knowledge.py` and regenerate the
   migration, since the vector column width is fixed. Tell me if you want to do this and I'll
   walk you through it.
4. Storage volumes: I added `vip_document_storage` for uploaded documents to
   `infra/docker-compose.yml`. The embedding model shares the same Hugging Face cache directory
   as Faster-Whisper (`whisper_model_cache`), so no extra volume was needed there — already handled.

## What's in Phase 4 — LLM grounded answer generation + refusal

When a customer sends a message (text **or** voice), the system now retrieves relevant
knowledge chunks and generates a grounded reply — or refuses.

New files:
- `app/services/llm/` — a provider-agnostic `LLMProvider` interface with `google`
  (Gemini, default), `anthropic` (Claude), and `mock` (offline) implementations, chosen by
  `LLM_PROVIDER`. `answering.py` holds the retrieve → threshold → prompt → generate logic.
- `app/models/message_source.py` — `MessageSource`: which chunk grounded which answer
  (similarity + rank). The spec's answer-traceability requirement.

Behaviour:
- `POST /api/v1/conversations/{id}/messages/text` and `.../messages/voice` now return
  `{ customer_message, assistant_message }`. The assistant message is a `role=system`
  `Message`; `assistant_message` also carries `answered`, `reason`, `provider`, `model`,
  `top_similarity`, and `sources[]`.
- **No hallucinated answers**: if the best retrieval similarity is below
  `RAG_CONFIDENCE_THRESHOLD` (0.78), or there are no documents, or the LLM call fails, the
  reply is a fixed human-handoff message ("let me connect you with a support
  representative") — the LLM is never called. `reason` is `low_confidence` /
  `no_documents` / `provider_error` vs `answered`.
- The reply is generated in the customer's detected language (English / Urdu / Roman Urdu).
- The LLM only ever sees the retrieved chunks as context, with instructions to answer from
  them alone.

### Configure the LLM

```bash
# in backend/.env
LLM_PROVIDER=google
GOOGLE_API_KEY=<from https://aistudio.google.com/apikey>
GEMINI_MODEL=gemini-2.5-flash
```

The Gemini API's free tier is generous for `gemini-2.5-flash` and is **separate** from a
Google AI Pro/Ultra subscription (that powers the Gemini app, not the API). To use Claude
instead: `uv pip install --python .venv anthropic`, then set `LLM_PROVIDER=anthropic` and
`ANTHROPIC_API_KEY`.

### Verification status

- ✅ **Verified end-to-end 2026-09-06** with real Gemini (`gemini-2.5-flash`) + Neon —
  `scripts/verify_phase4.py` 21/21, and by hand across all three languages:
  - EN: *"How do I check my balance?"* → *"...dial \*123# from your ACME SIM, or open the ACME app and tap Balance..."* (sim 0.86)
  - Roman Urdu: *"mera internet package activate kyun nahi ho raha hai?"* → *"Naya data package activate hone mein 15 minute tak lag sakte hain. Yaqeen karein ke aapka balance..."* (sim 0.82)
  - Urdu: *"میں اپنا نمبر ACME پر کیسے پورٹ کروں؟"* → *"667 پر PORT لکھ کر SMS بھیجیں۔ آپ کا نمبر 48 گھنٹوں میں پورٹ ہو جائے گا۔"* (sim 0.85)
  - Out of scope: *"Do you sell iPhones on installment?"* → sim 0.73 < 0.78 → human-handoff, LLM not called.
- Also verified 21/21 with `LLM_PROVIDER=mock` (no key needed — for CI / offline).

## What's in Phase 5 — Intent classification + entity extraction

Every customer message (text or voice) is now classified before the reply is generated.

- `app/services/nlu/intent.py` — one LLM call → `{intent, confidence, entities}`, via the
  same pluggable provider as Phase 4.
- `messages.intent` (`billing` / `technical_support` / `account_management` / `complaint` /
  `sales_inquiry` / `general_inquiry` / `other` / `unknown`), `messages.intent_confidence`,
  `messages.entities` (JSONB — `phone_numbers`, `amounts`, `package_or_product_names`,
  `dates_or_times`, `account_or_order_ids`, `locations`).
- `MessageOut` now carries these; system/assistant messages leave them null/empty.
- Classification failing (LLM down, rate-limited, bad JSON) logs a warning and stores
  `intent=unknown` — it never blocks the conversation.

### Verification status

- ✅ **Verified 2026-09-06** with `gemini-2.5-flash` — `scripts/verify_phase5.py` 20/20.
  Examples:
  - *"Why is my bill so high? I was charged 5000 rupees extra"* → `billing`, amounts `["5000 rupees"]`
  - *"I want to cancel the SIM for number 03001234567"* → `account_management`, phone_numbers `["03001234567"]`
  - *"I paid Rs. 2500 on 3rd January for the Super Weekly bundle ... account AC-99812"* →
    `billing`, amounts `["rs. 2500"]`, dates `["3rd january"]`, packages `["super weekly bundle"]`, ids `["ac-99812"]`
  - *"mujhe apna Lahore wala connection band karwana hai, number 0321-9998877"* →
    `account_management`, phone_numbers `["0321-9998877"]`, locations `["lahore"]`
- On the Gemini free tier, firing many messages back to back can hit the rate limit — those
  messages get `intent=unknown` (logged) rather than an error.

> **Gemini free-tier quota.** A Gemini API project with **no billing account linked** is
> capped at ~20 `gemini-2.5-flash` requests **per day**. Each customer message is 2–3 calls
> (classify + answer + optional TTS), so ~6 messages/day exhausts it and everything degrades
> to handoff / `unknown` (never an error). Fix: link a billing account in
> [AI Studio](https://aistudio.google.com/) — flash is ~$0.10 / 1M input tokens, so real
> usage for this project costs cents — or run with `LLM_PROVIDER=mock` / `TTS_PROVIDER=mock`
> for pipeline testing.

## What's in Phase 6 — TTS voice response

The assistant reply can now come back as speech.

- `app/services/tts/` — a `TTSProvider` interface (`google` = `gemini-2.5-flash-preview-tts`
  via the existing `GOOGLE_API_KEY`; `mock` = silent WAV). Gemini returns raw PCM; we wrap it
  in a WAV container. A per-language delivery instruction makes Roman Urdu come out as spoken
  Urdu, not spelled-out English.
- `POST /conversations/{id}/messages/voice` synthesizes the reply automatically (voice in →
  voice out); `POST .../messages/text/spoken` does the same for a typed message.
- `GET /conversations/{id}/messages/{message_id}/audio` returns the WAV — the customer's
  upload for their own messages, a synthesized-and-cached WAV for assistant replies.
- `audio_url` appears on `MessageOut` / `AssistantMessageOut` and in the transcript.

### Verification status

- ✅ **Verified 2026-09-06** — `scripts/verify_phase6.py` 10/10 with `TTS_PROVIDER=mock`
  (audio_url wiring, valid `RIFF/WAVE` bodies, on-demand synthesis, transcript, 404/401).
- Real `gemini-2.5-flash-preview-tts` confirmed producing 6–7 s, 24 kHz WAVs for English and
  Roman Urdu replies before the daily quota (above) cut testing short.

## What's in Phase 7 — Conversation analytics

Staff can summarize and assess a whole conversation, feeding the Phase 9 dashboards.

- `app/services/analytics/conversation.py` — one LLM pass over the transcript →
  `{summary, sentiment, resolution, follow_up}`.
- `conversations.sentiment` (`positive`/`neutral`/`negative`/`frustrated`), `.resolution`
  (`resolved`/`unresolved`/`needs_follow_up`/`escalated`), `.follow_up`, `.analyzed_at` —
  the AI's read, separate from `.status` (the manual open/resolved/escalated workflow).
- `GET /api/v1/conversations` — staff-only list for the dashboard (summary, sentiment,
  resolution, follow-up, message count; no message bodies).
- `PATCH /api/v1/conversations/{id}` — staff set the workflow status.
- `POST /api/v1/conversations/{id}/analyze` — run analysis; stores the fields and returns
  them plus a per-intent breakdown of the customer messages.

### Verification status

- ✅ **Verified 2026-09-06** — `scripts/verify_phase7.py` 19/19 with `LLM_PROVIDER=mock`
  (list + RBAC for `role=user`, status PATCH, `/analyze` persists
  summary/sentiment/resolution/analyzed_at and returns the intent breakdown, fields then
  visible on the conversation and the list, 404/401).
- Real-Gemini pass pending billing (see the quota note above).

## What's in Phase 8 — Self-learning: clustering + knowledge gaps + learning center

The controlled learning loop from the spec — repeated questions surface knowledge gaps,
admins approve new knowledge, and it becomes retrievable. **No automatic fine-tuning.**

- `app/services/learning/clustering.py` — greedy online clustering over customer-question
  embeddings (real `multilingual-e5`); centroids update by exact running mean. Each cluster's
  `is_gap` is set by retrieving its representative question against the KB: a gap is a cluster
  the knowledge base can't answer above `RAG_CONFIDENCE_THRESHOLD`.
- `QuestionCluster` / `QuestionClusterMember` tables; `DocumentType.curated` for
  learning-center answers.
- Endpoints (`/api/v1/learning/...`): `recluster`, `clusters` (filter `?status=` / `?gap=`),
  `gaps`, `clusters/{id}` (with member questions), `clusters/{id}/resolve` (admin approves an
  answer → chunked + embedded → retrievable now, cluster marked addressed),
  `clusters/{id}/dismiss`.

### Verification status

- ✅ **Verified 2026-09-06** — `scripts/verify_phase8.py` 19/19 with **real embeddings**
  (LLM mocked). Seeds a KB covering "check balance" but not "international roaming", sends
  three paraphrases of each: recluster groups them, the roaming cluster is flagged a gap
  (`top_kb_similarity` ≈ 0.68 < 0.78) and the balance one isn't; an admin resolves the gap
  with a curated answer that is immediately retrievable and lifts a fresh roaming question
  above the confidence threshold. Plus dismiss, admin-only RBAC, tenant isolation.
