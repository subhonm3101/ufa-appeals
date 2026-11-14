"""baseline: исходная схема из baseline_schema.sql (копия docs/schema.sql на момент начала проекта)

Revision ID: 0001
Revises:
"""
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = Path(__file__).resolve().parent.parent / "baseline_schema.sql"

# Справочники, без которых система не работает: на них опираются следующие миграции
# (подразделения привязываются к категориям). Нужны только новой пустой базе.
CATEGORIES = [
    ("roads", "Дороги и ямы", 0.8),
    ("lighting", "Уличное освещение", 0.6),
    ("transport", "Общественный транспорт", 0.7),
    ("other", "Прочие обращения", 0.3),
    ("garbage", "Мусор", 1.0),
    ("utilities", "ЖКХ", 1.0),
    ("landscaping", "Благоустройство", 1.0),
]
DISTRICTS = ["Дёмский", "Калининский", "Кировский", "Ленинский", "Октябрьский", "Орджоникидзевский", "Советский"]


def upgrade():
    bind = op.get_bind()
    # В базах, созданных раньше вручную из schema.sql, таблицы уже есть: ничего не трогаем.
    exists = bind.exec_driver_sql("SELECT to_regclass('public.appeals')").scalar()
    if exists is not None:
        return
    for statement in SCHEMA.read_text(encoding="utf-8").split(";"):
        if statement.strip():
            bind.exec_driver_sql(statement)
    for code, name, weight in CATEGORIES:
        op.execute(
            sa.text("INSERT INTO categories (code, name_ru, base_weight) VALUES (:c, :n, :w)").bindparams(
                c=code, n=name, w=weight
            )
        )
    for name in DISTRICTS:
        op.execute(sa.text("INSERT INTO districts (name) VALUES (:n)").bindparams(n=name))


def downgrade():
    pass
