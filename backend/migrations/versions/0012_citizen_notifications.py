"""Уведомления для граждан: новые виды уведомлений.

Revision ID: 0012
Revises: 0011
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

KINDS = "'assigned','status_changed','due_soon','overdue','appeal_update','citizen_comment'"


def upgrade():
    op.execute("ALTER TABLE notifications DROP CONSTRAINT IF EXISTS notifications_kind_check")
    op.execute(f"ALTER TABLE notifications ADD CONSTRAINT notifications_kind_check CHECK (kind IN ({KINDS}))")


def downgrade():
    op.execute("DELETE FROM notifications WHERE kind IN ('appeal_update','citizen_comment')")
    op.execute("ALTER TABLE notifications DROP CONSTRAINT IF EXISTS notifications_kind_check")
    op.execute(
        "ALTER TABLE notifications ADD CONSTRAINT notifications_kind_check "
        "CHECK (kind IN ('assigned','status_changed','due_soon','overdue'))"
    )
