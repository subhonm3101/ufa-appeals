import logging
from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..auth import CurrentUser, client_ip, require_roles
from ..db import get_session
from ..services.audit import log_event
from ..services.priority_features import compute_all


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/priority",
    tags=["priority"],
    dependencies=[
        Depends(require_roles("analyst", "manager", "admin"))
    ],
)

# Ключ блокировки: одновременно выполняется только один пересчёт.
RECALC_LOCK_KEY = 4207001
# Снимок приоритетов привязан к дате; время фиксировано, поэтому повторный
# пересчёт в тот же день заменяет снимок, а не добавляет новый.
SNAPSHOT_TIME = time(23, 59, 59)


@router.post("/recalculate")
def recalculate_priorities(
    request: Request,
    as_of_date: date | None = Query(
        None,
        alias="as_of",
        description="Дата снимка (по умолчанию сегодня, UTC); снимок строится на конец суток 23:59:59 UTC",
    ),
    user: CurrentUser = Depends(require_roles("manager", "admin")),
    session: Session = Depends(get_session),
):
    """Пересчитать и сохранить приоритеты методом rules_v1 на дату снимка."""
    today = datetime.now(timezone.utc).date()
    snapshot_date = as_of_date or today
    if snapshot_date > today:
        raise HTTPException(
            status_code=422,
            detail="Дата снимка не может быть в будущем",
        )
    as_of = datetime.combine(snapshot_date, SNAPSHOT_TIME, tzinfo=timezone.utc)

    try:
        session.execute(
            text("SELECT pg_advisory_xact_lock(:k)"), {"k": RECALC_LOCK_KEY}
        )
        results = compute_all(
            session=session,
            as_of=as_of,
            save=True,
        )
        # log_event фиксирует транзакцию вместе с пересчётом
        log_event(
            session,
            user.id,
            "priority_recalculate",
            "priority_scores",
            None,
            details={
                "method": "rules_v1",
                "as_of": as_of.isoformat(),
                "processed_clusters": len(results),
            },
            ip=client_ip(request),
        )
    except SQLAlchemyError:
        logger.exception("Пересчёт приоритетов не удался (as_of=%s)", as_of)
        session.rollback()
        raise HTTPException(
            status_code=503,
            detail="Не удалось пересчитать приоритеты",
        )

    return {
        "message": "Приоритеты успешно пересчитаны",
        "method": "rules_v1",
        "as_of": as_of,
        "processed_clusters": len(results),
    }


@router.get("/queue")
def priority_queue(
    district: str | None = Query(None, description="Название района"),
    category: str | None = Query(None, description="Код категории"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    """Очередь кластеров по последней оценке основного метода rules_v1."""
    filters = ["cl.status = 'open'"]  # закрытые кластеры в очередь не попадают
    params = {"limit": limit, "offset": offset}

    if district:
        filters.append("d.name = :district")
        params["district"] = district

    if category:
        filters.append("cat.code = :category")
        params["category"] = category

    where = ("WHERE " + " AND ".join(filters)) if filters else ""

    query = text(f"""
        WITH latest AS (
            SELECT DISTINCT ON (ps.cluster_id)
                ps.cluster_id,
                ps.score,
                ps.factors,
                ps.as_of,
                ps.calculated_at
            FROM priority_scores ps
            WHERE ps.method = 'rules_v1'
            ORDER BY
                ps.cluster_id,
                ps.as_of DESC NULLS LAST,
                ps.calculated_at DESC,
                ps.id DESC
        )
        SELECT
            cl.id AS cluster_id,
            latest.score,
            latest.factors,
            latest.as_of,
            latest.calculated_at,
            cl.status,
            cl.appeals_count,
            cl.centroid_lat,
            cl.centroid_lon,
            cat.code AS category,
            cat.name_ru AS category_name,
            d.name AS district
        FROM latest
        JOIN clusters cl ON cl.id = latest.cluster_id
        LEFT JOIN categories cat ON cat.id = cl.category_id
        LEFT JOIN districts d ON d.id = cl.district_id
        {where}
        ORDER BY latest.score DESC, cl.id
        LIMIT :limit OFFSET :offset
    """)

    count_query = text(f"""
        WITH latest AS (
            SELECT DISTINCT ON (ps.cluster_id)
                ps.cluster_id
            FROM priority_scores ps
            WHERE ps.method = 'rules_v1'
            ORDER BY
                ps.cluster_id,
                ps.as_of DESC NULLS LAST,
                ps.calculated_at DESC,
                ps.id DESC
        )
        SELECT COUNT(*)
        FROM latest
        JOIN clusters cl ON cl.id = latest.cluster_id
        LEFT JOIN categories cat ON cat.id = cl.category_id
        LEFT JOIN districts d ON d.id = cl.district_id
        {where}
    """)

    try:
        total = session.execute(
            count_query, params
        ).scalar_one()

        rows = session.execute(
            query, params
        ).mappings().all()

    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="База данных недоступна",
        )

    return {
        "items": [
            {
                "cluster_id": row["cluster_id"],
                "score": row["score"],
                "factors": row["factors"],
                "as_of": row["as_of"],
                "calculated_at": row["calculated_at"],
                "status": row["status"],
                "appeals_count": row["appeals_count"],
                "centroid_lat": row["centroid_lat"],
                "centroid_lon": row["centroid_lon"],
                "category": row["category"],
                "category_name": row["category_name"],
                "district": row["district"],
            }
            for row in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
        "method": "rules_v1",
    }


@router.get("/clusters/{cluster_id}")
def priority_cluster_details(
    cluster_id: int,
    session: Session = Depends(get_session),
):
    """Компоненты приоритета и обращения выбранного кластера."""

    try:
        cluster = session.execute(
            text("""
                SELECT
                    cl.id,
                    cl.status,
                    cl.appeals_count,
                    cl.centroid_lat,
                    cl.centroid_lon,
                    cl.first_seen,
                    cl.last_seen,
                    cat.code AS category,
                    cat.name_ru AS category_name,
                    d.name AS district,
                    ps.score,
                    ps.factors,
                    ps.as_of,
                    ps.calculated_at
                FROM clusters cl
                LEFT JOIN categories cat
                    ON cat.id = cl.category_id
                LEFT JOIN districts d
                    ON d.id = cl.district_id
                LEFT JOIN LATERAL (
                    SELECT
                        score,
                        factors,
                        as_of,
                        calculated_at
                    FROM priority_scores
                    WHERE cluster_id = cl.id
                      AND method = 'rules_v1'
                    ORDER BY
                        as_of DESC NULLS LAST,
                        calculated_at DESC,
                        id DESC
                    LIMIT 1
                ) ps ON TRUE
                WHERE cl.id = :cluster_id
            """),
            {"cluster_id": cluster_id},
        ).mappings().first()

        if cluster is None:
            raise HTTPException(
                status_code=404,
                detail="Кластер не найден",
            )

        appeals = session.execute(
            text("""
                SELECT
                    id,
                    external_id,
                    text,
                    created_at,
                    status,
                    lat,
                    lon
                FROM appeals
                WHERE cluster_id = :cluster_id
                ORDER BY created_at DESC, id DESC
            """),
            {"cluster_id": cluster_id},
        ).mappings().all()

    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="База данных недоступна",
        )

    result = dict(cluster)
    factors = result.pop("factors", None)

    result["components"] = (
        factors or {}
    ).get("components", {})

    result["factors"] = factors
    result["appeals"] = [
        dict(row) for row in appeals
    ]

    return result
