from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..auth import require_roles
from ..db import get_session


router = APIRouter(
    prefix="/api/anomalies",
    tags=["anomalies"],
    dependencies=[
        Depends(require_roles("analyst", "manager", "admin"))
    ],
)

# Подряд идущие аномальные дни одного ряда (категория x район) склеиваются в событие.
EVENTS_CTE = """
    WITH base AS (
        SELECT a.category_id, a.district_id, a.day, a.observed, a.expected, a.score,
               a.day - (ROW_NUMBER() OVER (
                   PARTITION BY a.category_id, a.district_id ORDER BY a.day
               ))::int AS grp
        FROM anomalies a
        LEFT JOIN categories cat ON cat.id = a.category_id
        LEFT JOIN districts d ON d.id = a.district_id
        {inner_where}
    ),
    ev AS (
        SELECT category_id, district_id,
               MIN(day) AS start_day, MAX(day) AS end_day, COUNT(*) AS days,
               MAX(observed) AS peak, MAX(expected) AS expected, MAX(score) AS score
        FROM base
        GROUP BY category_id, district_id, grp
    )
"""


@router.get("")
def list_anomalies(
    district: str | None = Query(None, description="Название района"),
    category: str | None = Query(None, description="Код категории"),
    date_from: date | None = Query(None, description="События, заканчивающиеся не раньше"),
    date_to: date | None = Query(None, description="События, начинающиеся не позже"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    """События аномального роста обращений (по числу новых проблем за 7 дней)."""
    inner, outer = [], []
    params = {"limit": limit, "offset": offset}
    if district:
        inner.append("d.name = :district")
        params["district"] = district
    if category:
        inner.append("cat.code = :category")
        params["category"] = category
    if date_from:
        outer.append("ev.end_day >= :date_from")
        params["date_from"] = date_from
    if date_to:
        outer.append("ev.start_day <= :date_to")
        params["date_to"] = date_to

    cte = EVENTS_CTE.format(
        inner_where=("WHERE " + " AND ".join(inner)) if inner else ""
    )
    outer_where = ("WHERE " + " AND ".join(outer)) if outer else ""

    page_sql = text(f"""
        {cte}
        SELECT ev.start_day, ev.end_day, ev.days, ev.peak, ev.expected, ev.score,
               cat.code AS category, cat.name_ru AS category_name, d.name AS district
        FROM ev
        LEFT JOIN categories cat ON cat.id = ev.category_id
        LEFT JOIN districts d ON d.id = ev.district_id
        {outer_where}
        ORDER BY ev.start_day DESC, ev.category_id
        LIMIT :limit OFFSET :offset
    """)
    count_sql = text(f"""
        {cte}
        SELECT COUNT(*) FROM ev {outer_where}
    """)

    try:
        total = session.execute(count_sql, params).scalar_one()
        rows = session.execute(page_sql, params).mappings().all()
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="База данных недоступна")

    return {
        "items": [
            {
                "category": r["category"],
                "category_name": r["category_name"],
                "district": r["district"],
                "start": r["start_day"],
                "end": r["end_day"],
                "days": r["days"],
                "peak": r["peak"],
                "expected": round(float(r["expected"]), 2),
                "score": round(float(r["score"]), 2),
            }
            for r in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
        "method": "poisson_new_clusters_7d",
    }
