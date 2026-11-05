"""Рабочий процесс обработки обращений: статусы и история, подразделения,
исполнители, комментарии, публичный номер.

Revision ID: 0007
Revises: 0006
"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

STATUSES = "'new','accepted','in_progress','waiting','resolved','rejected'"


def upgrade():
    # --- подразделения -----------------------------------------------------
    op.execute(
        """
        CREATE TABLE departments (
            id SERIAL PRIMARY KEY,
            code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL UNIQUE,
            is_active BOOLEAN NOT NULL DEFAULT TRUE
        )
        """
    )
    op.execute(
        """
        CREATE TABLE department_categories (
            department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
            category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
            PRIMARY KEY (department_id, category_id)
        )
        """
    )
    # Начальная структура: по одному подразделению на категорию.
    # Администратор может перестроить её позже.
    op.execute(
        """
        INSERT INTO departments (code, name)
        SELECT DISTINCT ON (code) code, 'Отдел: ' || name_ru
        FROM categories
        ORDER BY code, id
        """
    )
    op.execute(
        """
        INSERT INTO department_categories (department_id, category_id)
        SELECT d.id, c.id
        FROM categories c
        JOIN departments d ON d.code = c.code
        """
    )

    # --- пользователи: подразделение и роль исполнителя -------------------
    op.execute(
        "ALTER TABLE users ADD COLUMN department_id INTEGER REFERENCES departments(id)"
    )
    op.execute("ALTER TABLE users DROP CONSTRAINT users_role_check")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT users_role_check "
        "CHECK (role IN ('operator','analyst','manager','admin','executor'))"
    )

    # --- обращения: новые поля ---------------------------------------------
    op.execute(
        """
        ALTER TABLE appeals
            ADD COLUMN public_number TEXT,
            ADD COLUMN source TEXT NOT NULL DEFAULT 'import',
            ADD COLUMN address_text TEXT,
            ADD COLUMN contact_email TEXT,
            ADD COLUMN department_id INTEGER REFERENCES departments(id),
            ADD COLUMN assignee_id INTEGER REFERENCES users(id),
            ADD COLUMN due_at TIMESTAMPTZ,
            ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            ADD COLUMN resolved_at TIMESTAMPTZ,
            ADD COLUMN response_text TEXT
        """
    )
    op.execute(
        "ALTER TABLE appeals ADD CONSTRAINT appeals_source_check "
        "CHECK (source IN ('import','web','operator','api'))"
    )
    op.execute(
        f"ALTER TABLE appeals ADD CONSTRAINT appeals_status_check "
        f"CHECK (status IN ({STATUSES}))"
    )

    # Публичный номер: UFA-<год>-<id>. Присваивается триггером при вставке,
    # поэтому импорт и любые другие способы создания работают без изменений.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION appeals_set_public_number() RETURNS trigger AS $$
        BEGIN
            IF NEW.public_number IS NULL THEN
                NEW.public_number := 'UFA-'
                    || to_char(NEW.created_at AT TIME ZONE 'Asia/Yekaterinburg', 'YYYY')
                    || '-' || lpad(NEW.id::text, 6, '0');
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_appeals_public_number
        BEFORE INSERT ON appeals
        FOR EACH ROW EXECUTE FUNCTION appeals_set_public_number()
        """
    )

    # Задним числом для уже загруженных обращений.
    op.execute(
        """
        UPDATE appeals
        SET public_number = 'UFA-'
            || to_char(created_at AT TIME ZONE 'Asia/Yekaterinburg', 'YYYY')
            || '-' || lpad(id::text, 6, '0')
        """
    )
    op.execute(
        """
        UPDATE appeals a
        SET department_id = dc.department_id
        FROM department_categories dc
        WHERE dc.category_id = a.category_id
        """
    )
    op.execute("ALTER TABLE appeals ALTER COLUMN public_number SET NOT NULL")
    op.execute(
        "CREATE UNIQUE INDEX uq_appeals_public_number ON appeals (public_number)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_appeals_status ON appeals (status)")
    op.execute("CREATE INDEX idx_appeals_assignee ON appeals (assignee_id)")
    op.execute("CREATE INDEX idx_appeals_department ON appeals (department_id)")
    op.execute("CREATE INDEX idx_appeals_due_at ON appeals (due_at)")

    # --- история статусов и комментарии ------------------------------------
    op.execute(
        """
        CREATE TABLE appeal_status_history (
            id BIGSERIAL PRIMARY KEY,
            appeal_id BIGINT NOT NULL REFERENCES appeals(id) ON DELETE CASCADE,
            from_status TEXT,
            to_status TEXT NOT NULL,
            changed_by INTEGER REFERENCES users(id),
            comment TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_status_history_appeal ON appeal_status_history (appeal_id, created_at)"
    )
    op.execute(
        """
        INSERT INTO appeal_status_history (appeal_id, from_status, to_status, comment, created_at)
        SELECT id, NULL, COALESCE(status, 'new'), 'Обращение загружено в систему', created_at
        FROM appeals
        """
    )
    op.execute(
        """
        CREATE TABLE appeal_comments (
            id BIGSERIAL PRIMARY KEY,
            appeal_id BIGINT NOT NULL REFERENCES appeals(id) ON DELETE CASCADE,
            author_id INTEGER REFERENCES users(id),
            body TEXT NOT NULL,
            is_internal BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_appeal_comments_appeal ON appeal_comments (appeal_id, created_at)"
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS appeal_comments")
    op.execute("DROP TABLE IF EXISTS appeal_status_history")
    op.execute("DROP TRIGGER IF EXISTS trg_appeals_public_number ON appeals")
    op.execute("DROP FUNCTION IF EXISTS appeals_set_public_number()")
    op.execute("DROP INDEX IF EXISTS idx_appeals_status")
    op.execute("ALTER TABLE appeals DROP CONSTRAINT IF EXISTS appeals_status_check")
    op.execute("ALTER TABLE appeals DROP CONSTRAINT IF EXISTS appeals_source_check")
    op.execute(
        """
        ALTER TABLE appeals
            DROP COLUMN IF EXISTS public_number,
            DROP COLUMN IF EXISTS source,
            DROP COLUMN IF EXISTS address_text,
            DROP COLUMN IF EXISTS contact_email,
            DROP COLUMN IF EXISTS department_id,
            DROP COLUMN IF EXISTS assignee_id,
            DROP COLUMN IF EXISTS due_at,
            DROP COLUMN IF EXISTS updated_at,
            DROP COLUMN IF EXISTS resolved_at,
            DROP COLUMN IF EXISTS response_text
        """
    )
    op.execute("ALTER TABLE users DROP CONSTRAINT users_role_check")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT users_role_check "
        "CHECK (role IN ('operator','analyst','manager','admin'))"
    )
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS department_id")
    op.execute("DROP TABLE IF EXISTS department_categories")
    op.execute("DROP TABLE IF EXISTS departments")
