FROM python:3.11-slim

WORKDIR /code

# ffmpeg: Faster-Whisper audio decoding. gcc/libpq-dev: psycopg2 build.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn==23.0.0

COPY . .

# run as a non-root user
RUN useradd -m app && chown -R app /code
USER app

# model + upload caches (mounted as volumes in compose / by the platform)
ENV HF_HOME=/code/.cache/huggingface
RUN mkdir -p /code/.cache/huggingface /code/storage/audio /code/storage/documents /code/storage/tts

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
    CMD curl -fsS http://localhost:8000/health || exit 1

# WEB_CONCURRENCY controls worker count (default 2). Each worker loads the
# embedding model, so size it against available RAM (~2.5 GB/worker).
CMD ["sh", "-c", "alembic upgrade head && gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w ${WEB_CONCURRENCY:-2} -b 0.0.0.0:8000 --timeout 120"]
