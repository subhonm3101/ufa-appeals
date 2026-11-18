"""Пустой кластер удаляется вместе с последним обращением; убираем уже осиротевшие кластеры."""
from alembic import op

revision = "0016_drop_empty_clusters"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE OR REPLACE FUNCTION drop_empty_cluster() RETURNS trigger AS $$
        BEGIN
            IF OLD.cluster_id IS NOT NULL
               AND NOT EXISTS (SELECT 1 FROM appeals WHERE cluster_id = OLD.cluster_id) THEN
                BEGIN
                    DELETE FROM priority_scores WHERE cluster_id = OLD.cluster_id;
                    DELETE FROM clusters WHERE id = OLD.cluster_id;
                EXCEPTION WHEN foreign_key_violation THEN
                    NULL;  -- на кластер ссылаются другие данные: оставляем
                END;
            END IF;
            RETURN NULL;
        END
        $$ LANGUAGE plpgsql
    """)
    op.execute("DROP TRIGGER IF EXISTS trg_drop_empty_cluster ON appeals")
    op.execute(
        "CREATE TRIGGER trg_drop_empty_cluster AFTER DELETE ON appeals "
        "FOR EACH ROW EXECUTE FUNCTION drop_empty_cluster()"
    )
    # кластеры без обращений (остатки удалённых обращений)
    op.execute(
        "DELETE FROM priority_scores WHERE cluster_id IN "
        "(SELECT c.id FROM clusters c WHERE NOT EXISTS (SELECT 1 FROM appeals a WHERE a.cluster_id = c.id))"
    )
    op.execute(
        "DELETE FROM clusters c WHERE NOT EXISTS (SELECT 1 FROM appeals a WHERE a.cluster_id = c.id)"
    )


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS trg_drop_empty_cluster ON appeals")
    op.execute("DROP FUNCTION IF EXISTS drop_empty_cluster()")
