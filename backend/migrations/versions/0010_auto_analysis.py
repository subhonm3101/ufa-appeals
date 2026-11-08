"""Автоанализ обращений при поступлении: признак ручной проверки.

Revision ID: 0010
Revises: 0009
"""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE appeals ADD COLUMN needs_review BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute(
        "CREATE INDEX idx_appeals_needs_review ON appeals (id) WHERE needs_review"
    )
    # результаты анализа удаляются вместе с обращением
    op.execute("ALTER TABLE appeal_predictions DROP CONSTRAINT appeal_predictions_appeal_id_fkey")
    op.execute(
        "ALTER TABLE appeal_predictions ADD CONSTRAINT appeal_predictions_appeal_id_fkey "
        "FOREIGN KEY (appeal_id) REFERENCES appeals(id) ON DELETE CASCADE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_predictions_appeal ON appeal_predictions (appeal_id)"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_predictions_appeal")
    op.execute("ALTER TABLE appeal_predictions DROP CONSTRAINT appeal_predictions_appeal_id_fkey")
    op.execute(
        "ALTER TABLE appeal_predictions ADD CONSTRAINT appeal_predictions_appeal_id_fkey "
        "FOREIGN KEY (appeal_id) REFERENCES appeals(id)"
    )
    op.execute("DROP INDEX IF EXISTS idx_appeals_needs_review")
    op.execute("ALTER TABLE appeals DROP COLUMN IF EXISTS needs_review")
