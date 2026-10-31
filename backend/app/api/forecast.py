from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..auth import require_roles
from ..db import get_session


router = APIRouter(
    prefix="/api/forecast",
    tags=["forecast"],
    dependencies=[
        Depends(require_roles("analyst", "manager", "admin"))
    ],
)


@router.get("")
def get_forecast(
    granularity: Literal["day", "week"] = Query(
        "week", description="Единица прогноза: day (28 дней) или week (4 недели)"
    ),
    category: str | None = Query(None, description="Код категории"),
    district: str | None = Query(None, description="Название района"),
    session: Session = Depends(get_session),
):
    """Прогноз нагрузки с 80% интервалом: город, категория или район.

    Без фильтров возвращается прогноз по городу. Прогноз по парам
    категория x район не публикуется (ряды слишком разрежены, см. Э6).
    """
    if category and district:
        raise HTTPException(
            status_code=422,
            detail="Прогноз по паре категория x район не публикуется: "
                   "укажите либо категорию, либо район",
        )

    try:
        category_id = district_id = None
        if category:
            category_id = session.execute(
                text("SELECT id FROM categories WHERE code = :c"), {"c": category}
            ).scalar_one_or_none()
            if category_id is None:
                raise HTTPException(status_code=404, detail="Категория не найдена")
        if district:
            district_id = session.execute(
                text("SELECT id FROM districts WHERE name = :n"), {"n": district}
            ).scalar_one_or_none()
            if district_id is None:
                raise HTTPException(status_code=404, detail="Район не найден")

        model = session.execute(
            text("""
                SELECT f.model_id, m.name, m.version, m.metrics,
                       MAX(f.made_at) AS made_at
                FROM forecasts f
                JOIN ml_models m ON m.id = f.model_id
                WHERE f.granularity = :g
                GROUP BY f.model_id, m.name, m.version, m.metrics
                ORDER BY MAX(f.made_at) DESC
                LIMIT 1
            """),
            {"g": granularity},
        ).mappings().first()
        if model is None:
            raise HTTPException(status_code=404, detail="Прогноз ещё не рассчитан")

        rows = session.execute(
            text("""
                SELECT target_date, value, lower, upper
                FROM forecasts
                WHERE model_id = :m
                  AND granularity = :g
                  AND category_id IS NOT DISTINCT FROM :cid
                  AND district_id IS NOT DISTINCT FROM :did
                ORDER BY target_date
            """),
            {"m": model["model_id"], "g": granularity,
             "cid": category_id, "did": district_id},
        ).mappings().all()
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="База данных недоступна")

    level = "category" if category else "district" if district else "city"
    return {
        "granularity": granularity,
        "level": level,
        "category": category,
        "district": district,
        "model": {
            "id": model["model_id"],
            "name": model["name"],
            "version": model["version"],
            "metrics": model["metrics"],
            "made_at": model["made_at"],
        },
        "items": [
            {
                "target_date": r["target_date"],
                "value": round(float(r["value"]), 2),
                "lower": round(float(r["lower"]), 2),
                "upper": round(float(r["upper"]), 2),
            }
            for r in rows
        ],
    }
