from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

# pool_pre_ping: revalidate a pooled connection before use (hosted Postgres like
#   Neon closes idle connections; without this the first query after an idle gap
#   raises "SSL connection has been closed unexpectedly").
# pool_recycle: proactively drop connections older than 5 min so we rarely hand
#   out one the server has already timed out.
engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=300)
# expire_on_commit=False: after commit, keep attribute values in memory instead
# of forcing a re-SELECT on next access. With Python-side defaults for id /
# timestamps (see base_class), a write endpoint can build its response without an
# extra round-trip. Each request gets a fresh session, so staleness isn't a risk.
SessionLocal = sessionmaker(
    autocommit=False, autoflush=False, expire_on_commit=False, bind=engine
)
