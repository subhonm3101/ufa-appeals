"""baseline: схема создана вручную из docs/schema.sql

Revision ID: 0001
Revises:
"""
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Таблицы уже созданы файлом docs/schema.sql. Эта ревизия только фиксирует
    # начальное состояние: для существующей базы выполните `alembic stamp 0001`.
    pass


def downgrade():
    pass
