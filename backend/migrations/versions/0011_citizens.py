"""Роль «гражданин» и привязка обращений к гражданину.

Revision ID: 0011
Revises: 0010
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE users DROP CONSTRAINT users_role_check")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT users_role_check "
        "CHECK (role IN ('operator','analyst','manager','admin','executor','citizen'))"
    )
    op.execute(
        "ALTER TABLE appeals ADD COLUMN citizen_id INTEGER REFERENCES users(id) ON DELETE SET NULL"
    )
    op.execute("CREATE INDEX idx_appeals_citizen ON appeals (citizen_id) WHERE citizen_id IS NOT NULL")


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_appeals_citizen")
    op.execute("ALTER TABLE appeals DROP COLUMN IF EXISTS citizen_id")
    op.execute("DELETE FROM users WHERE role = 'citizen'")
    op.execute("ALTER TABLE users DROP CONSTRAINT users_role_check")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT users_role_check "
        "CHECK (role IN ('operator','analyst','manager','admin','executor'))"
    )
