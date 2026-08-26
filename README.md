# Phase 1 — Backend Skeleton

FastAPI + PostgreSQL(pgvector) + Redis + Docker + JWT auth + RBAC + core models
(Organization, User, Customer).

## Run it

```bash
cd backend
cp .env.example .env        # edit SECRET_KEY at minimum
cd ../infra
docker compose up --build
```

Backend will be available at http://localhost:8000
Interactive API docs: http://localhost:8000/docs

## Run the first migration

Once containers are up, in a second terminal:

```bash
docker exec -it vip_backend bash
alembic revision --autogenerate -m "init: organizations, users, customers"
alembic upgrade head
exit
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
