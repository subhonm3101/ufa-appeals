"""Уведомления внутри системы.

Revision ID: 0008
Revises: 0007
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE notifications (
            id BIGSERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            appeal_id BIGINT REFERENCES appeals(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK (kind IN ('assigned','status_changed','due_soon','overdue')),
            message TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            read_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_notifications_user ON notifications (user_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX idx_notifications_unread ON notifications (user_id) WHERE read_at IS NULL"
    )
    # напоминания о сроках приходят один раз на пару «пользователь, обращение, вид»
    op.execute(
        "CREATE UNIQUE INDEX uq_notifications_deadline ON notifications (user_id, appeal_id, kind) "
        "WHERE kind IN ('due_soon','overdue')"
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS notifications")
