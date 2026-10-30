"""экспертная разметка приоритета кластеров: таблица expert_labels

Revision ID: 0005
Revises: 0004
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS expert_labels (
            id BIGSERIAL PRIMARY KEY,
            cluster_id INTEGER NOT NULL REFERENCES clusters(id),
            rating REAL NOT NULL,
            r1 REAL,
            r2 REAL,
            orientation TEXT,
            as_of TIMESTAMPTZ NOT NULL,
            source TEXT NOT NULL DEFAULT 'self_two_rounds',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_expert_labels UNIQUE (cluster_id, as_of, source)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_expert_labels_cluster ON expert_labels (cluster_id)")


def downgrade():
    op.execute("DROP TABLE IF EXISTS expert_labels")
