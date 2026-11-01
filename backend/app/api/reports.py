"""Отчёт в Excel: сводка, динамика, прогноз, аномалии, очередь приоритетов."""
import json
import logging
from datetime import date, datetime, timedelta
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..auth import CurrentUser, client_ip, require_roles
from ..db import get_session
from ..services.audit import log_event
from ..services.importer import LOCAL_TZ
from .anomalies import EVENTS_CTE

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reports", tags=["reports"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_DAYS = 3660
DEFAULT_DAYS = 90
PRIORITY_ROWS = 100

HEADER_FILL = PatternFill("solid", fgColor="2F6FED")
HEADER_FONT = Font(bold=True, color="FFFFFF")
DATE_FMT = "DD.MM.YYYY"

COMPONENTS = [
    ("urgency", "Срочность"),
    ("scale", "Масштаб"),
    ("significance", "Значимость"),
    ("dynamics", "Динамика"),
    ("age", "Возраст"),
]
LEVELS = {"city": "Город", "category": "Категория", "district": "Район"}
GRAN = {"day": "День", "week": "Неделя (начало)"}


def _table(ws, row: int, headers: list, rows: list, formats: dict | None = None) -> int:
    """Пишет таблицу с заголовком; возвращает номер последней строки."""
    for j, h in enumerate(headers, 1):
        cell = ws.cell(row=row, column=j, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    for i, values in enumerate(rows, row + 1):
        for j, v in enumerate(values, 1):
            cell = ws.cell(row=i, column=j, value=v)
            if formats and j in formats:
                cell.number_format = formats[j]
    return row + len(rows)


def _widths(ws, min_w: int = 10, max_w: int = 60) -> None:
    for col in ws.columns:
        letter = get_column_letter(col[0].column)
        longest = max((len(str(c.value)) for c in col if c.value is not None), default=0)
        ws.column_dimensions[letter].width = min(max(longest + 2, min_w), max_w)


def _category_totals(session: Session, d0: date, d1: date, cid, did) -> list[dict]:
    rows = session.execute(
        text("""
            SELECT c.code, c.name_ru, COALESCE(SUM(a.cnt), 0) AS n
            FROM aggregates_daily a
            JOIN categories c ON c.id = a.category_id
            WHERE a.day BETWEEN :d0 AND :d1
              AND (CAST(:cid AS int) IS NULL OR a.category_id = :cid)
              AND (CAST(:did AS int) IS NULL OR a.district_id = :did)
            GROUP BY c.id, c.code, c.name_ru
            ORDER BY c.id
        """),
        {"d0": d0, "d1": d1, "cid": cid, "did": did},
    ).mappings().all()
    return [dict(r) for r in rows]


def _daily(session: Session, d0: date, d1: date, cid, did) -> list[tuple]:
    return [
        (r[0], int(r[1]))
        for r in session.execute(
            text("""
                SELECT a.day, COALESCE(SUM(a.cnt), 0)
                FROM aggregates_daily a
                WHERE a.day BETWEEN :d0 AND :d1
                  AND (CAST(:cid AS int) IS NULL OR a.category_id = :cid)
                  AND (CAST(:did AS int) IS NULL OR a.district_id = :did)
                GROUP BY a.day ORDER BY a.day
            """),
            {"d0": d0, "d1": d1, "cid": cid, "did": did},
        ).all()
    ]


def _forecast_rows(session: Session, cid, did) -> list[tuple]:
    rows = session.execute(
        text("""
            SELECT f.granularity, f.category_id, f.district_id,
                   c.name_ru AS category, d.name AS district,
                   f.target_date, f.value, f.lower, f.upper
            FROM forecasts f
            LEFT JOIN categories c ON c.id = f.category_id
            LEFT JOIN districts d ON d.id = f.district_id
            WHERE f.model_id = (
                SELECT f2.model_id FROM forecasts f2
                WHERE f2.granularity = f.granularity
                ORDER BY f2.made_at DESC LIMIT 1
            )
              AND (
                (CAST(:cid AS int) IS NULL AND CAST(:did AS int) IS NULL)
                OR (f.category_id IS NULL AND f.district_id IS NULL)
                OR f.category_id = :cid
                OR f.district_id = :did
              )
            ORDER BY f.granularity DESC,
                     (f.category_id IS NOT NULL), (f.district_id IS NOT NULL),
                     c.name_ru NULLS FIRST, d.name NULLS FIRST, f.target_date
        """),
        {"cid": cid, "did": did},
    ).mappings().all()
    out = []
    for r in rows:
        level = "category" if r["category_id"] else "district" if r["district_id"] else "city"
        obj = r["category"] or r["district"] or "—"
        out.append((GRAN.get(r["granularity"], r["granularity"]), LEVELS[level], obj,
                    r["target_date"], r["value"], r["lower"], r["upper"]))
    return out


def _anomaly_rows(session: Session, d0: date, d1: date, category, district) -> list[tuple]:
    inner, params = [], {"d0": d0, "d1": d1}
    if district:
        inner.append("d.name = :district")
        params["district"] = district
    if category:
        inner.append("cat.code = :category")
        params["category"] = category
    cte = EVENTS_CTE.format(inner_where=("WHERE " + " AND ".join(inner)) if inner else "")
    rows = session.execute(
        text(f"""
            {cte}
            SELECT cat.name_ru AS category, d.name AS district,
                   ev.start_day, ev.end_day, ev.days, ev.peak, ev.expected, ev.score
            FROM ev
            LEFT JOIN categories cat ON cat.id = ev.category_id
            LEFT JOIN districts d ON d.id = ev.district_id
            WHERE ev.end_day >= :d0 AND ev.start_day <= :d1
            ORDER BY ev.start_day DESC, ev.category_id
        """),
        params,
    ).mappings().all()
    return [(r["category"], r["district"], r["start_day"], r["end_day"], r["days"],
             r["peak"], round(float(r["expected"]), 2), round(float(r["score"]), 2))
            for r in rows]


def _priority_rows(session: Session, category, district) -> list[tuple]:
    filters, params = [], {"limit": PRIORITY_ROWS}
    if district:
        filters.append("d.name = :district")
        params["district"] = district
    if category:
        filters.append("cat.code = :category")
        params["category"] = category
    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    rows = session.execute(
        text(f"""
            WITH latest AS (
                SELECT DISTINCT ON (ps.cluster_id)
                    ps.cluster_id, ps.score, ps.factors, ps.as_of
                FROM priority_scores ps
                WHERE ps.method = 'rules_v1'
                ORDER BY ps.cluster_id, ps.as_of DESC NULLS LAST,
                         ps.calculated_at DESC, ps.id DESC
            )
            SELECT latest.cluster_id, latest.score, latest.factors, latest.as_of,
                   cl.appeals_count, cat.name_ru AS category, d.name AS district
            FROM latest
            JOIN clusters cl ON cl.id = latest.cluster_id
            LEFT JOIN categories cat ON cat.id = cl.category_id
            LEFT JOIN districts d ON d.id = cl.district_id
            {where}
            ORDER BY latest.score DESC, cl.id
            LIMIT :limit
        """),
        params,
    ).mappings().all()
    out = []
    for n, r in enumerate(rows, 1):
        factors = r["factors"]
        if isinstance(factors, str):
            factors = json.loads(factors)
        weights = (factors or {}).get("weights", {})
        comps = (factors or {}).get("components", {})
        parts = [round(100 * float(weights.get(k, 0)) * float(comps.get(k, 0)), 1)
                 for k, _ in COMPONENTS]
        as_of = r["as_of"].date() if r["as_of"] else None
        out.append((n, r["cluster_id"], r["category"], r["district"], r["appeals_count"],
                    round(float(r["score"]), 1), *parts, as_of))
    return out


@router.get("/summary.xlsx")
def summary_report(
    request: Request,
    date_from: date | None = Query(None, description="Начало периода (по умолчанию 90 дней до конца данных)"),
    date_to: date | None = Query(None, description="Конец периода (по умолчанию последний день данных)"),
    category: str | None = Query(None, description="Код категории"),
    district: str | None = Query(None, description="Название района"),
    user: CurrentUser = Depends(require_roles("analyst", "manager", "admin")),
    session: Session = Depends(get_session),
):
    """Отчёт по обращениям в формате Excel."""
    try:
        cid = did = None
        category_name = district_name = None
        if category:
            row = session.execute(text("SELECT id, name_ru FROM categories WHERE code = :c"),
                                  {"c": category}).first()
            if row is None:
                raise HTTPException(status_code=404, detail="Категория не найдена")
            cid, category_name = row
        if district:
            row = session.execute(text("SELECT id, name FROM districts WHERE name = :n"),
                                  {"n": district}).first()
            if row is None:
                raise HTTPException(status_code=404, detail="Район не найден")
            did, district_name = row

        last_day = session.execute(text("SELECT MAX(day) FROM aggregates_daily")).scalar_one()
        d1 = date_to or last_day or datetime.now(LOCAL_TZ).date()
        d0 = date_from or d1 - timedelta(days=DEFAULT_DAYS - 1)
        if d0 > d1:
            raise HTTPException(status_code=422, detail="Начало периода позже его конца")
        days = (d1 - d0).days + 1
        if days > MAX_DAYS:
            raise HTTPException(status_code=422, detail=f"Период не должен превышать {MAX_DAYS} дней")
        p1, p0 = d0 - timedelta(days=1), d0 - timedelta(days=days)

        cur = _category_totals(session, d0, d1, cid, did)
        prev = {r["code"]: int(r["n"]) for r in _category_totals(session, p0, p1, cid, did)}
        daily = _daily(session, d0, d1, cid, did)
        forecast = _forecast_rows(session, cid, did)
        anomalies = _anomaly_rows(session, d0, d1, category, district)
        priorities = _priority_rows(session, category, district)
    except SQLAlchemyError:
        logger.exception("Не удалось собрать отчёт")
        session.rollback()
        raise HTTPException(status_code=503, detail="Не удалось сформировать отчёт")

    total = sum(int(r["n"]) for r in cur)
    prev_total = sum(prev.values())
    now = datetime.now(LOCAL_TZ)

    wb = Workbook()

    # --- Сводка ---
    ws = wb.active
    ws.title = "Сводка"
    ws["A1"] = "Отчёт по обращениям граждан, г. Уфа"
    ws["A1"].font = Font(bold=True, size=14)
    info = [
        ("Период", f"{d0:%d.%m.%Y} – {d1:%d.%m.%Y} ({days} дн.)"),
        ("Категория", category_name or "все"),
        ("Район", district_name or "все"),
        ("Сформирован", now.strftime("%d.%m.%Y %H:%M")),
        ("Сформировал", getattr(user, "full_name", None) or user.email),
        ("Обращений за период", total),
        ("В среднем в день", round(total / days, 1)),
        (f"Предыдущий период ({p0:%d.%m.%Y} – {p1:%d.%m.%Y})", prev_total),
        ("Изменение", (total - prev_total) / prev_total if prev_total else None),
    ]
    for i, (k, v) in enumerate(info, 3):
        ws.cell(row=i, column=1, value=k).font = Font(bold=True)
        cell = ws.cell(row=i, column=2, value=v)
        if k == "Изменение":
            cell.number_format = "+0.0%;-0.0%;0.0%"
        elif isinstance(v, float):
            cell.number_format = "0.0"
    start = 3 + len(info) + 1
    rows = []
    for r in cur:
        n = int(r["n"])
        p = prev.get(r["code"], 0)
        rows.append((r["name_ru"], n, (n / total) if total else 0.0, p,
                     ((n - p) / p) if p else None))
    _table(ws, start, ["Категория", "Обращений", "Доля", "Предыдущий период", "Изменение"], rows,
           {3: "0.0%", 5: "+0.0%;-0.0%;0.0%"})
    _widths(ws)

    # --- Динамика ---
    ws = wb.create_sheet("Динамика")
    last = _table(ws, 1, ["Дата", "Обращений"], daily, {1: DATE_FMT})
    if daily:
        chart = LineChart()
        chart.title = "Обращения по дням"
        chart.height, chart.width = 8, 24
        chart.add_data(Reference(ws, min_col=2, min_row=1, max_row=last), titles_from_data=True)
        chart.set_categories(Reference(ws, min_col=1, min_row=2, max_row=last))
        chart.x_axis.number_format = "dd.mm"
        chart.x_axis.delete = False
        chart.y_axis.delete = False
        ws.add_chart(chart, "D2")
    _widths(ws)

    # --- Прогноз ---
    ws = wb.create_sheet("Прогноз")
    _table(ws, 1, ["Единица", "Уровень", "Объект", "Дата", "Прогноз", "Нижняя граница 80%",
                   "Верхняя граница 80%"], forecast, {4: DATE_FMT, 5: "0.0", 6: "0.0", 7: "0.0"})
    _widths(ws)

    # --- Аномалии ---
    ws = wb.create_sheet("Аномалии")
    _table(ws, 1, ["Категория", "Район", "Начало", "Конец", "Дней", "Пик за 7 дней", "Обычно",
                   "Оценка (0-10)"], anomalies, {3: DATE_FMT, 4: DATE_FMT})
    _widths(ws)

    # --- Приоритеты ---
    ws = wb.create_sheet("Приоритеты")
    headers = ["№", "Проблема", "Категория", "Район", "Обращений", "Балл"]
    headers += [f"{label} (баллы)" for _, label in COMPONENTS] + ["Расчёт на"]
    _table(ws, 1, headers, priorities, {11: DATE_FMT})
    _widths(ws)

    buf = BytesIO()
    wb.save(buf)

    log_event(
        session, user.id, "report_export", "report", None,
        details={"kind": "summary_xlsx", "date_from": str(d0), "date_to": str(d1),
                 "category": category, "district": district},
        ip=client_ip(request),
    )
    return Response(
        content=buf.getvalue(),
        media_type=XLSX,
        headers={"Content-Disposition": f'attachment; filename="appeals_report_{d0}_{d1}.xlsx"'},
    )
