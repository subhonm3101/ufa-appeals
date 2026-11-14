"""Отзыв токенов доступа: версия токена у пользователя.

Revision ID: 0014
Revises: 0013
"""
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0")
    # Смена пароля (сам пользователь или администратор) и отключение учётной записи
    # аннулируют все выданные токены: версия растёт автоматически, в любом месте кода.
    op.execute(
        """
        CREATE FUNCTION bump_token_version() RETURNS trigger AS $$
        BEGIN
            IF NEW.token_version = OLD.token_version
               AND (NEW.password_hash IS DISTINCT FROM OLD.password_hash
                    OR (OLD.is_active AND NOT NEW.is_active)) THEN
                NEW.token_version = OLD.token_version + 1;
            END IF;
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER trg_users_token_version BEFORE UPDATE ON users "
        "FOR EACH ROW EXECUTE FUNCTION bump_token_version()"
    )


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS trg_users_token_version ON users")
    op.execute("DROP FUNCTION IF EXISTS bump_token_version()")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS token_version")
