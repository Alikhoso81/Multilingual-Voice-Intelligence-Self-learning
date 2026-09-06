"""
Multilingual text embedding service.

Default model: intfloat/multilingual-e5-large (1024-dim), per the project's
architecture spec — chosen because it embeds English, Urdu, and Roman Urdu
into one shared vector space, which is exactly what cross-language retrieval
and clustering need.

IMPORTANT — resource reality check:
  multilingual-e5-large is a ~2.2GB model and is noticeably slow on CPU-only
  machines (a few seconds per embedding call). If your machine struggles:
    - Set EMBEDDING_MODEL_NAME=intfloat/multilingual-e5-small in .env
      (much smaller/faster, still multilingual, somewhat lower retrieval quality).
    - If you switch model size, you MUST also update EMBEDDING_DIM in
      app/models/knowledge.py to match (e5-small = 384 dims, e5-base = 768,
      e5-large = 1024) and regenerate the migration, since the vector column
      width is fixed at the database level.
  This is exactly the kind of empirical tradeoff flagged in the architecture
  doc — test on your own machine before committing to a model size.

e5 models require a task prefix on the input text ("query: " for search
queries, "passage: " for documents being indexed) — this is documented model
behavior, not a bug; omitting it measurably hurts retrieval quality.
"""
import os
from functools import lru_cache

from sentence_transformers import SentenceTransformer

EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "intfloat/multilingual-e5-large")


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    return SentenceTransformer(EMBEDDING_MODEL_NAME)


def embed_passage(text: str) -> list[float]:
    """Embed a document chunk for storage (indexing side of retrieval)."""
    model = _get_model()
    vector = model.encode(f"passage: {text}", normalize_embeddings=True)
    return vector.tolist()


def embed_query(text: str) -> list[float]:
    """Embed a user question for similarity search (query side of retrieval)."""
    model = _get_model()
    vector = model.encode(f"query: {text}", normalize_embeddings=True)
    return vector.tolist()


def embed_passages_batch(texts: list[str]) -> list[list[float]]:
    """Batch version — more efficient than calling embed_passage in a loop."""
    if not texts:
        return []
    model = _get_model()
    vectors = model.encode(
        [f"passage: {t}" for t in texts], normalize_embeddings=True, batch_size=16
    )
    return vectors.tolist()
