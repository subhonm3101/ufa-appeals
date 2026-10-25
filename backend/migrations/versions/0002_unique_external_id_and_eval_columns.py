"""уникальный external_id; колонки problem_id и subtopic (эталон для экспериментов)

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    # Эталонная разметка синтетического набора: нужна только для оценки качества
    # (эксперименты Э1, Э2), в логике системы не используется.
    op.execute("ALTER TABLE appeals ADD COLUMN IF NOT EXISTS problem_id TEXT")
    op.execute("ALTER TABLE appeals ADD COLUMN IF NOT EXISTS subtopic TEXT")
    # Защита от дублей при повторной загрузке одного и того же файла.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_appeals_external_id "
        "ON appeals (external_id) WHERE external_id IS NOT NULL"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_appeals_problem_id ON appeals (problem_id)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_appeals_problem_id")
    op.execute("DROP INDEX IF EXISTS uq_appeals_external_id")
    op.execute("ALTER TABLE appeals DROP COLUMN IF EXISTS subtopic")
    op.execute("ALTER TABLE appeals DROP COLUMN IF EXISTS problem_id")
