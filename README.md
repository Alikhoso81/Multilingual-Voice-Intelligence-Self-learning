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

## Not in Phase 1 (coming in later phases)

Conversations/messages, voice, intents, RAG, clustering, analytics, admin dashboard UI —
per the roadmap, these land in Phases 2–10.
