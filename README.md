# Multilingual Voice Intelligence & Self-Learning Knowledge Platform

Enterprise customer-support AI that takes voice/text in **English, Urdu, Roman Urdu and
mixed Urdu-English**, transcribes and language-detects it, answers from company documents
via RAG (grounded, no hallucinations), detects knowledge gaps, and lets admins approve new
knowledge before it becomes retrievable.

**Stack:** Python + FastAPI · PostgreSQL + pgvector · Faster-Whisper (ASR) ·
`multilingual-e5-large` embeddings · Claude API (LLM) · Redis + Celery · Docker.

## Phase status

| Phase | Scope | Status |
|---|---|---|
| 1 | Backend + DB + auth skeleton | ✅ done |
| 2 | Voice→text + language detection/normalization | ✅ code done (voice upload not yet user-tested) |
| 3 | Document ingestion + pgvector + RAG retrieval | ✅ code done — see "Running Phase 3" below |
| 4 | LLM grounded answer generation + refusal behavior | ⬜ next |
| 5 | Intent classification + entity extraction | ⬜ |
| 6 | TTS voice response | ⬜ |
| 7 | Conversation analytics (summary/sentiment/resolution) | ⬜ |
| 8 | Question clustering + knowledge-gap detection + learning center | ⬜ |
| 9 | Full admin + agent dashboards | ⬜ |
| 10 | Security hardening, evaluation harness, deployment, benchmarking | ⬜ |

## Run it

```bash
cd backend
cp .env.example .env        # then edit .env: set a real SECRET_KEY (and ANTHROPIC_API_KEY from Phase 4)
cd ../infra
docker compose up --build
```

Backend: http://localhost:8000 · Interactive API docs: http://localhost:8000/docs

## Run migrations

Once containers are up, in a second terminal:

```bash
docker exec -it vip_backend bash
alembic upgrade head          # applies the committed migration(s) — no autogenerate needed
exit
```

The repo ships a single consolidated init migration covering the whole schema through
Phase 3. If your dev database was created by an **older** migration and `alembic upgrade
head` complains about a missing/!mismatched revision, reset the volume (dev data is
disposable):

```bash
docker compose down -v        # drops the Postgres volume — also fixes leftover ENUM types
docker compose up --build
docker exec -it vip_backend bash -c "alembic upgrade head"
```

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

```bash
cd infra
docker compose down -v          # only if you have an old dev DB — see "Run migrations"
docker compose up --build
# second terminal:
docker exec -it vip_backend bash -c "alembic upgrade head"
```

Then at http://localhost:8000/docs (log in first — reuse the Phase 1 flow to get a Bearer
token for an **admin** user):

1. `POST /api/v1/knowledge/documents` — upload a small `.txt` or `.pdf` (e.g. an FAQ).
   First upload downloads the ~2.2 GB embedding model — expect several minutes once.
2. `GET /api/v1/knowledge/documents` — confirm `status: "ready"` and `chunk_count > 0`.
3. `POST /api/v1/knowledge/search` with `{"query": "<something from your doc>", "top_k": 5}`
   — you should get chunks back ranked by `similarity`.

### Verification status

- Built and unit-tested by Claude (chat) in a sandbox with the embedding model **mocked**:
  parsing (TXT/CSV/DOCX), chunking, cosine ranking, and the full HTTP flow (upload → store →
  list → search, RBAC 403 for non-admins, 400 for unsupported types) all pass.
- **Not yet run by the user** against a real Postgres + real embedding model. The migration
  now explicitly enables the `vector` extension (this was missing and would have failed on a
  fresh pgvector image). Treat Phase 3 as unverified until the steps above pass locally.

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
