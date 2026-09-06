"""phase 7: conversation analytics fields

Revision ID: cd1494022c72
Revises: cf52531e1fae
Create Date: 2026-09-06 13:22:52.903597

"""
from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'cd1494022c72'
down_revision = 'cf52531e1fae'
branch_labels = None
depends_on = None

sentiment = postgresql.ENUM(
    'positive', 'neutral', 'negative', 'frustrated', 'unknown',
    name='conversationsentiment',
)
resolution = postgresql.ENUM(
    'resolved', 'unresolved', 'needs_follow_up', 'escalated', 'unknown',
    name='conversationresolution',
)


def upgrade() -> None:
    bind = op.get_bind()
    sentiment.create(bind, checkfirst=True)
    resolution.create(bind, checkfirst=True)
    op.add_column('conversations', sa.Column('sentiment', sentiment, nullable=True))
    op.add_column('conversations', sa.Column('resolution', resolution, nullable=True))
    op.add_column('conversations', sa.Column('follow_up', sa.Text(), nullable=True))
    op.add_column('conversations', sa.Column('analyzed_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('conversations', 'analyzed_at')
    op.drop_column('conversations', 'follow_up')
    op.drop_column('conversations', 'resolution')
    op.drop_column('conversations', 'sentiment')
    bind = op.get_bind()
    resolution.drop(bind, checkfirst=True)
    sentiment.drop(bind, checkfirst=True)
