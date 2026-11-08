"""Вложения к обращениям (фотографии).

Revision ID: 0009
Revises: 0008
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE appeal_attachments (
            id BIGSERIAL PRIMARY KEY,
            appeal_id BIGINT NOT NULL REFERENCES appeals(id) ON DELETE CASCADE,
            original_name TEXT NOT NULL,
            content_type TEXT NOT NULL,
            size_bytes INTEGER NOT NULL CHECK (size_bytes > 0),
            storage_name TEXT NOT NULL UNIQUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_attachments_appeal ON appeal_attachments (appeal_id)")


def downgrade():
    op.execute("DROP TABLE IF EXISTS appeal_attachments")
