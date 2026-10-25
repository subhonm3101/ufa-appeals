"""Аналитика для дашборда: ряды по времени, сводка, тепловая карта, точки на карте.

Все даты считаются по времени Уфы (UTC+5). Границы периода включительные: date_from и date_to.
"""
from datetime import date, datetime, time, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..db import get_session
from ..schemas import (
    CategoryOut, CategoryStat, DistrictStat, Heatmap, HeatmapCell, MapPoint, MapPoints,
    Summary, TimePoint, TimeSeries,
)
from ..services.importer import LOCAL_TZ

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

TZ_NAME = "Asia/Yekaterinburg"
DEFAULT_DAYS = 90
MAX_RANGE_DAYS = 366 * 5
Granularity = Literal["day", "week", "month"]


def _start(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=LOCAL_TZ)


def _pct(cur: int, prev: int) -> float | None:
    return round((cur - prev) / prev * 100, 1) if prev else None


def resolve_range(session: Session, date_from: date | None, date_to: date | None) -> tuple[date, date]:
    """По умолчанию: последние 90 дней, заканчивая последним днём, за который есть данные."""
    if date_to is None:
        last = session.execute(
            text("SELECT CAST(MAX(created_at AT TIME ZONE :tz) AS date) FROM appeals"), {"tz": TZ_NAME}
        ).scalar()
        date_to = last or date.today()
    if date_from is None:
        date_from = date_to - timedelta(days=DEFAULT_DAYS - 1)
    if date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from не может быть позже date_to")
    if (date_to - date_from).days + 1 > MAX_RANGE_DAYS:
        raise HTTPException(status_code=422, detail="Период не может быть длиннее 5 лет")
    return date_from, date_to


def _check_refs(session: Session, category: str | None, district: str | None) -> None:
    if category and not session.execute(text("SELECT 1 FROM categories WHERE code = :c"), {"c": category}).first():
        raise HTTPException(status_code=404, detail=f"Категория '{category}' не найдена")
    if district and not session.execute(text("SELECT 1 FROM districts WHERE name = :d"), {"d": district}).first():
        raise HTTPException(status_code=404, detail=f"Район '{district}' не найден")


def _filters(category: str | None, district: str | None) -> tuple[str, dict]:
    sql, params = "", {}
    if category:
        sql += " AND c.code = :category"
        params["category"] = category
    if district:
        sql += " AND d.name = :district"
        params["district"] = district
    return sql, params


JOINS = "LEFT JOIN categories c ON c.id = a.category_id LEFT JOIN districts d ON d.id = a.district_id"


@router.get("/timeseries", response_model=TimeSeries)
def timeseries(
    date_from: date | None = Query(None, description="По умолчанию: 90 дней до последней даты в данных"),
    date_to: date | None = None,
    granularity: Granularity = "day",
    category: str | None = Query(None, description="Код категории"),
    district: str | None = Query(None, description="Название района"),
    session: Session = Depends(get_session),
):
    """Число обращений по периодам. Периоды без обращений возвращаются с нулём.
    Недели начинаются с понедельника; крайние периоды при week/month могут быть неполными."""
    try:
        date_from, date_to = resolve_range(session, date_from, date_to)
        _check_refs(session, category, district)
        extra, params = _filters(category, district)
        g = granularity  # значение из белого списка Literal, подставлять в SQL безопасно
        rows = session.execute(
            text(f"""
            WITH series AS (
              SELECT generate_series(date_trunc('{g}', CAST(:d_from AS timestamp)),
                                     date_trunc('{g}', CAST(:d_to AS timestamp)),
                                     interval '1 {g}') AS period
            ), counts AS (
              SELECT date_trunc('{g}', a.created_at AT TIME ZONE :tz) AS period, COUNT(*) AS cnt
              FROM appeals a {JOINS}
              WHERE a.created_at >= :ts_from AND a.created_at < :ts_to {extra}
              GROUP BY 1
            )
            SELECT CAST(s.period AS date) AS period, COALESCE(c.cnt, 0) AS count
            FROM series s LEFT JOIN counts c ON c.period = s.period
            ORDER BY s.period
            """),
            {"d_from": date_from, "d_to": date_to, "tz": TZ_NAME,
             "ts_from": _start(date_from), "ts_to": _start(date_to + timedelta(days=1)), **params},
        ).all()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="База данных недоступна") from exc
    points = [TimePoint(period=r.period, count=r.count) for r in rows]
    return TimeSeries(
        date_from=date_from, date_to=date_to, granularity=granularity, category=category,
        district=district, total=sum(p.count for p in points), points=points,
    )


@router.get("/summary", response_model=Summary)
def summary(
    date_from: date | None = None,
    date_to: date | None = None,
    session: Session = Depends(get_session),
):
    """Сводка для карточек дашборда: итого, сравнение с предыдущим периодом такой же длины,
    разбивка по категориям и районам (в том числе рост и падение в процентах)."""
    try:
        date_from, date_to = resolve_range(session, date_from, date_to)
        days = (date_to - date_from).days + 1
        prev_from, prev_to = date_from - timedelta(days=days), date_from - timedelta(days=1)
        p = {"f": _start(date_from), "t": _start(date_to + timedelta(days=1)), "pf": _start(prev_from)}

        tot = session.execute(
            text("""
            SELECT COUNT(*) FILTER (WHERE created_at >= :f AND created_at < :t) AS cur,
                   COUNT(*) FILTER (WHERE created_at >= :pf AND created_at < :f) AS prev,
                   COUNT(*) FILTER (WHERE created_at >= :f AND created_at < :t AND category_id IS NULL) AS uncat
            FROM appeals WHERE created_at >= :pf AND created_at < :t
            """), p,
        ).one()
        cats = session.execute(
            text("""
            SELECT c.code, c.name_ru AS name,
                   COUNT(a.id) FILTER (WHERE a.created_at >= :f AND a.created_at < :t) AS cnt,
                   COUNT(a.id) FILTER (WHERE a.created_at >= :pf AND a.created_at < :f) AS prev
            FROM categories c
            LEFT JOIN appeals a ON a.category_id = c.id AND a.created_at >= :pf AND a.created_at < :t
            GROUP BY c.id, c.code, c.name_ru ORDER BY cnt DESC, c.id
            """), p,
        ).all()
        dists = session.execute(
            text("""
            SELECT d.name,
                   COUNT(a.id) FILTER (WHERE a.created_at >= :f AND a.created_at < :t) AS cnt,
                   COUNT(a.id) FILTER (WHERE a.created_at >= :pf AND a.created_at < :f) AS prev
            FROM districts d
            LEFT JOIN appeals a ON a.district_id = d.id AND a.created_at >= :pf AND a.created_at < :t
            GROUP BY d.name ORDER BY cnt DESC, d.name
            """), p,
        ).all()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="База данных недоступна") from exc
    return Summary(
        date_from=date_from, date_to=date_to, prev_date_from=prev_from, prev_date_to=prev_to,
        days=days, total=tot.cur, prev_total=tot.prev, change_pct=_pct(tot.cur, tot.prev),
        per_day=round(tot.cur / days, 2), uncategorized=tot.uncat,
        by_category=[
            CategoryStat(code=r.code, name=r.name, count=r.cnt, prev_count=r.prev,
                         change_pct=_pct(r.cnt, r.prev), share=round(r.cnt / tot.cur, 4) if tot.cur else 0.0)
            for r in cats
        ],
        by_district=[
            DistrictStat(name=r.name, count=r.cnt, prev_count=r.prev, change_pct=_pct(r.cnt, r.prev))
            for r in dists
        ],
    )


@router.get("/heatmap", response_model=Heatmap)
def heatmap(
    date_from: date | None = None,
    date_to: date | None = None,
    session: Session = Depends(get_session),
):
    """Матрица «категория × район» за период (для тепловой карты)."""
    try:
        date_from, date_to = resolve_range(session, date_from, date_to)
        cells = session.execute(
            text("""
            SELECT c.code AS category, d.name AS district, COUNT(*) AS cnt
            FROM appeals a JOIN categories c ON c.id = a.category_id JOIN districts d ON d.id = a.district_id
            WHERE a.created_at >= :f AND a.created_at < :t
            GROUP BY c.code, d.name ORDER BY c.code, d.name
            """),
            {"f": _start(date_from), "t": _start(date_to + timedelta(days=1))},
        ).all()
        cats = session.execute(text("SELECT code, name_ru FROM categories ORDER BY id")).all()
        dists = session.execute(text("SELECT DISTINCT name FROM districts ORDER BY name")).all()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="База данных недоступна") from exc
    return Heatmap(
        date_from=date_from, date_to=date_to,
        categories=[CategoryOut(code=r.code, name=r.name_ru) for r in cats],
        districts=[r.name for r in dists],
        cells=[HeatmapCell(category=r.category, district=r.district, count=r.cnt) for r in cells],
    )


@router.get("/points", response_model=MapPoints)
def points(
    date_from: date | None = None,
    date_to: date | None = None,
    category: str | None = None,
    district: str | None = None,
    limit: int = Query(2000, ge=1, le=5000),
    session: Session = Depends(get_session),
):
    """Обращения с координатами для карты (самые свежие первыми)."""
    try:
        date_from, date_to = resolve_range(session, date_from, date_to)
        _check_refs(session, category, district)
        extra, params = _filters(category, district)
        base = (
            f"FROM appeals a {JOINS} WHERE a.created_at >= :ts_from AND a.created_at < :ts_to "
            f"AND a.lat IS NOT NULL AND a.lon IS NOT NULL {extra}"
        )
        params |= {"ts_from": _start(date_from), "ts_to": _start(date_to + timedelta(days=1))}
        total = session.execute(text("SELECT COUNT(*) " + base), params).scalar_one()
        rows = session.execute(
            text("SELECT a.id, a.lat, a.lon, c.code AS category, d.name AS district, a.created_at " + base +
                 " ORDER BY a.created_at DESC, a.id DESC LIMIT :limit"),
            {**params, "limit": limit},
        ).mappings().all()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="База данных недоступна") from exc
    return MapPoints(total=total, items=[MapPoint(**r) for r in rows])
