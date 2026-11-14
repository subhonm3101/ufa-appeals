"""Ограничение частоты запросов в базе данных.

Revision ID: 0015
Revises: 0014
"""
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE rate_hits (
            id BIGSERIAL PRIMARY KEY,
            bucket TEXT NOT NULL,
            key TEXT NOT NULL,
            at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_rate_hits ON rate_hits (bucket, key, at)")


def downgrade():
    op.execute("DROP TABLE IF EXISTS rate_hits")
