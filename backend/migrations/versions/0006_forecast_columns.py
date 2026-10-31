"""forecasts: granularity (day/week), made_at, index

Revision ID: 0006
Revises: 0005
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        ALTER TABLE forecasts
            ADD COLUMN IF NOT EXISTS granularity TEXT NOT NULL DEFAULT 'day',
            ADD COLUMN IF NOT EXISTS made_at TIMESTAMPTZ NOT NULL DEFAULT now();
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_forecasts_model_target "
        "ON forecasts (model_id, granularity, target_date)"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_forecasts_model_target")
    op.execute(
        """
        ALTER TABLE forecasts
            DROP COLUMN IF EXISTS made_at,
            DROP COLUMN IF EXISTS granularity;
        """
    )
