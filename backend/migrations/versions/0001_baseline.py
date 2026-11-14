"""baseline: исходная схема из baseline_schema.sql (копия docs/schema.sql на момент начала проекта)

Revision ID: 0001
Revises:
"""
from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = Path(__file__).resolve().parent.parent / "baseline_schema.sql"


def upgrade():
    bind = op.get_bind()
    # В базах, созданных раньше вручную из schema.sql, таблицы уже есть: ничего не трогаем.
    exists = bind.exec_driver_sql("SELECT to_regclass('public.appeals')").scalar()
    if exists is not None:
        return
    for statement in SCHEMA.read_text(encoding="utf-8").split(";"):
        if statement.strip():
            bind.exec_driver_sql(statement)


def downgrade():
    pass
