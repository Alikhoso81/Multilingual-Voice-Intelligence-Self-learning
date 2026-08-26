# Import all models here so Alembic autogenerate can discover them via Base.metadata
from app.models.organization import Organization  # noqa
from app.models.user import User, UserRole  # noqa
from app.models.customer import Customer  # noqa
