from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..db import get_session
from ..schemas import AppealOut, AppealsPage, CategoryOut, DistrictOut, ImportReport
from ..services.importer import LOCAL_TZ, MAX_BYTES, ImportFileError, run_import

router = APIRouter(prefix="/api", tags=["appeals"])

DB_DOWN = HTTPException(status_code=503, detail="База данных недоступна")


@router.post("/import", response_model=ImportReport)
def import_appeals(
    file: UploadFile = File(..., description="Файл .csv или .xlsx"),
    dry_run: bool = Query(False, description="Только проверить файл, в базу ничего не писать"),
    session: Session = Depends(get_session),
):
    """Загрузка обращений из CSV/XLSX. Пока без авторизации (она появится на шаге 3.4)."""
    content = file.file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"Файл больше {MAX_BYTES // (1024 * 1024)} МБ")
    try:
        return run_import(session, file.filename or "upload", content, dry_run)
    except ImportFileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise DB_DOWN from exc


@router.get("/appeals", response_model=AppealsPage)
def list_appeals(
    category: str | None = Query(None, description="Код категории, например roads"),
    district: str | None = Query(None, description="Название района"),
    date_from: date | None = Query(None, description="С даты включительно"),
    date_to: date | None = Query(None, description="По дату включительно"),
    q: str | None = Query(None, max_length=200, description="Поиск по тексту"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    where, params = ["TRUE"], {}
    if category:
        where.append("c.code = :category")
        params["category"] = category
    if district:
        where.append("d.name = :district")
        params["district"] = district
    if date_from:
        where.append("a.created_at >= :date_from")
        params["date_from"] = datetime.combine(date_from, time.min, tzinfo=LOCAL_TZ)
    if date_to:
        where.append("a.created_at < :date_to")
        params["date_to"] = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=LOCAL_TZ)
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where.append("a.text ILIKE :q ESCAPE '\\'")
        params["q"] = f"%{escaped}%"

    base = (
        "FROM appeals a LEFT JOIN categories c ON c.id = a.category_id "
        "LEFT JOIN districts d ON d.id = a.district_id WHERE " + " AND ".join(where)
    )
    try:
        total = session.execute(text("SELECT COUNT(*) " + base), params).scalar_one()
        rows = session.execute(
            text(
                "SELECT a.id, a.external_id, a.text, a.created_at, d.name AS district, "
                "c.code AS category, a.lat, a.lon " + base +
                " ORDER BY a.created_at DESC, a.id DESC LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": limit, "offset": offset},
        ).mappings().all()
    except SQLAlchemyError as exc:
        raise DB_DOWN from exc
    return AppealsPage(total=total, limit=limit, offset=offset, items=[AppealOut(**r) for r in rows])


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(session: Session = Depends(get_session)):
    try:
        rows = session.execute(text("SELECT code, name_ru FROM categories ORDER BY id")).all()
    except SQLAlchemyError as exc:
        raise DB_DOWN from exc
    return [CategoryOut(code=r.code, name=r.name_ru) for r in rows]


@router.get("/districts", response_model=list[DistrictOut])
def list_districts(session: Session = Depends(get_session)):
    try:
        rows = session.execute(text("SELECT MIN(id) AS id, name FROM districts GROUP BY name ORDER BY name")).all()
    except SQLAlchemyError as exc:
        raise DB_DOWN from exc
    return [DistrictOut(id=r.id, name=r.name) for r in rows]
