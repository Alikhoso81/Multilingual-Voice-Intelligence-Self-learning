# Deployment (Phase 10)

Three ways to run it. All need one database (Neon or any Postgres 14+ with the
`vector` extension available) and a `GOOGLE_API_KEY`.

## 1. Local (dev) — uv + Neon

See the README "Run it → Option A". Fastest for development.

## 2. Docker Compose — everything in containers

```bash
cd backend && cp .env.example .env      # set SECRET_KEY and GOOGLE_API_KEY
cd ../infra && docker compose up --build
```

Brings up Postgres (pgvector), Redis, and the backend. `alembic upgrade head`
runs on container start. Dashboard at http://localhost:8000/app/.

- `WEB_CONCURRENCY` (compose sets `1`) = gunicorn workers. **Each worker loads the
  ~2.2 GB embedding model**, so budget ~2.5 GB RAM per worker.
- The `hf_model_cache` volume keeps the model between restarts (first request
  still downloads it once).

## 3. PaaS (Render / Fly / Railway) + Neon

`infra/render.yaml` is a ready blueprint. General steps for any platform:

1. **Database**: create a free [Neon](https://neon.tech) project. Connection string
   goes in `DATABASE_URL` as `postgresql+psycopg2://…?sslmode=require`.
2. **Build**: Docker, `dockerfilePath: backend/Dockerfile`, context `backend/`.
3. **Env**: `ENV=production`, `SECRET_KEY` (generate a strong one),
   `GOOGLE_API_KEY`, `LLM_PROVIDER=google`, `ALLOW_OPEN_REGISTRATION=false`,
   `ALLOWED_ORIGINS=["https://your-domain"]`, `WEB_CONCURRENCY=1`.
4. **Health check**: `GET /health`.
5. **First admin**: with open registration off, seed one out of band:
   ```bash
   # against the deployed DB
   DATABASE_URL=... .venv/Scripts/python scripts/create_admin.py "Org Name" admin@you.com 'password'
   ```

### ⚠️ Memory

`intfloat/multilingual-e5-large` needs **~2.5 GB RAM**. Free tiers (Render 512 MB,
Fly 256 MB shared) will OOM. Options:

- Use a paid instance with ≥ 3 GB (Render Standard, Fly `shared-cpu-1x` 2 GB is
  still tight — prefer 4 GB).
- Or switch to the small model: set `EMBEDDING_MODEL_NAME=intfloat/multilingual-e5-small`,
  change `EMBEDDING_DIM = 1024` → `384` in `app/models/knowledge.py` and in the
  `QuestionCluster.centroid` column, regenerate the init migration, and start from
  a fresh database. Retrieval quality drops somewhat; RAM drops to ~600 MB.

## Production checklist

- [ ] `ENV=production` (enforces a non-default `SECRET_KEY`, enables HSTS)
- [ ] `ALLOW_OPEN_REGISTRATION=false`, first admin seeded via `scripts/create_admin.py`
- [ ] `ALLOWED_ORIGINS` set to the real dashboard origin
- [ ] `GOOGLE_API_KEY` project has **billing linked** (the free tier is ~20 req/day)
- [ ] `RATE_LIMIT_ENABLED=true` (default), tuned via `RATE_LIMIT_PER_MINUTE`
- [ ] Rate limiter is in-process — with `WEB_CONCURRENCY > 1` move it to Redis
- [ ] DB in the same region as the app (see `scripts/benchmark.py` — cross-region
      round-trips dominate request latency)
- [ ] Back up the Postgres database (Neon does point-in-time on paid plans)
