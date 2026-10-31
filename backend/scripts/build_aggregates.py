"""Шаг 6.1: заполнение aggregates_daily (день x категория x район).

Дни считаются по времени Уфы (UTC+5). Дни без обращений записываются нулями.
Скрипт можно запускать повторно: таблица каждый раз пересчитывается целиком.

Запуск из корня проекта:
    python backend\\scripts\\build_aggregates.py
"""
import os
import sys

from sqlalchemy import create_engine, text

URL = os.environ.get(
    "APPEALS_DATABASE_URL",
    "postgresql+psycopg2://appeals:appeals@127.0.0.1:5433/appeals",
)
TZ = "Asia/Yekaterinburg"

SQL_RANGE = text(
    "SELECT min((created_at AT TIME ZONE :tz)::date), "
    "max((created_at AT TIME ZONE :tz)::date) FROM appeals "
    "WHERE category_id IS NOT NULL AND district_id IS NOT NULL"
)

SQL_FILL = text(
    """
    INSERT INTO aggregates_daily (day, category_id, district_id, cnt)
    SELECT d::date, c.id, r.id, COALESCE(x.n, 0)
    FROM generate_series(CAST(:d0 AS date), CAST(:d1 AS date), interval '1 day') AS d
    CROSS JOIN (SELECT DISTINCT category_id AS id FROM appeals
                WHERE category_id IS NOT NULL) c
    CROSS JOIN (SELECT DISTINCT district_id AS id FROM appeals
                WHERE district_id IS NOT NULL) r
    LEFT JOIN (
        SELECT (created_at AT TIME ZONE :tz)::date AS day,
               category_id, district_id, count(*) AS n
        FROM appeals
        WHERE category_id IS NOT NULL AND district_id IS NOT NULL
        GROUP BY 1, 2, 3
    ) x ON x.day = d::date AND x.category_id = c.id AND x.district_id = r.id
    """
)


def main() -> int:
    engine = create_engine(URL)
    with engine.begin() as conn:
        d0, d1 = conn.execute(SQL_RANGE, {"tz": TZ}).one()
        if d0 is None:
            print("Нет обращений с категорией и районом, агрегировать нечего.")
            return 1
        conn.execute(text("DELETE FROM aggregates_daily"))
        conn.execute(SQL_FILL, {"d0": d0, "d1": d1, "tz": TZ})
        rows, total, nonzero = conn.execute(
            text("SELECT count(*), sum(cnt), count(*) FILTER (WHERE cnt > 0) "
                 "FROM aggregates_daily")
        ).one()
        expected = conn.execute(
            text("SELECT count(*) FROM appeals "
                 "WHERE category_id IS NOT NULL AND district_id IS NOT NULL")
        ).scalar_one()
    print(f"Период: {d0} .. {d1}")
    print(f"Строк в aggregates_daily: {rows}, из них с обращениями: {nonzero}")
    print(f"Сумма cnt: {total}, обращений в appeals: {expected}")
    if total != expected:
        print("ОШИБКА: суммы не совпадают")
        return 2
    print("OK: суммы совпадают")
    return 0


if __name__ == "__main__":
    sys.exit(main())
