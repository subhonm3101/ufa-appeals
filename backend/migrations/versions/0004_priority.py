"""приоритизация: метод и момент расчёта в priority_scores, индексы по cluster_id

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE priority_scores ADD COLUMN IF NOT EXISTS method TEXT NOT NULL DEFAULT 'rules_v1'")
    op.execute("ALTER TABLE priority_scores ADD COLUMN IF NOT EXISTS as_of TIMESTAMPTZ")
    op.execute("CREATE INDEX IF NOT EXISTS idx_priority_scores_cluster ON priority_scores (cluster_id, calculated_at)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_appeals_cluster_id ON appeals (cluster_id)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_appeals_cluster_id")
    op.execute("DROP INDEX IF EXISTS idx_priority_scores_cluster")
    op.execute("ALTER TABLE priority_scores DROP COLUMN IF EXISTS as_of")
    op.execute("ALTER TABLE priority_scores DROP COLUMN IF EXISTS method")