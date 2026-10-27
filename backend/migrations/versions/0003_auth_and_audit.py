"""авторизация и журнал действий: is_active, last_login_at, details, ip

Revision ID: 0003
Revises: 0002
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ")
    op.execute("ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS details JSONB")
    op.execute("ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS ip TEXT")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_log (created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log (action)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_audit_action")
    op.execute("DROP INDEX IF EXISTS idx_audit_created_at")
    op.execute("ALTER TABLE audit_log DROP COLUMN IF EXISTS ip")
    op.execute("ALTER TABLE audit_log DROP COLUMN IF EXISTS details")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS last_login_at")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_active")
