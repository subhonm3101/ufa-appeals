"""Внешний API для интеграции с другими системами (ключ в заголовке X-API-Key)."""
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..auth import client_ip
from ..db import get_session
from ..services import apikeys, intake
from ..services.ratelimit import RateLimiter
from .public import NUMBER, STATUS_RU

router = APIRouter(prefix="/api/external", tags=["external"])

key_limiter = RateLimiter(limit=300, window=600)
bad_key_limiter = RateLimiter(limit=30, window=600)

UNAUTHORIZED = HTTPException(status_code=401, detail="Неверный или отозванный ключ API")


class ExternalAppeal(BaseModel):
    text: str = Field(max_length=6000)
    external_id: str = Field(min_length=1, max_length=100)
    address_text: str | None = Field(None, max_length=400)
    contact_email: str | None = Field(None, max_length=300)
    district_id: int | None = None
    lat: float | None = None
    lon: float | None = None


def api_key(
    request: Request,
    x_api_key: str | None = Header(None),
    session: Session = Depends(get_session),
):
    """Проверяет ключ; возвращает его id. Подбор ключей ограничен по IP."""
    ip = client_ip(request)
    if not x_api_key:
        if not bad_key_limiter.allow(ip):
            raise HTTPException(status_code=429, detail="Слишком много запросов. Попробуйте позже.")
        raise UNAUTHORIZED
    try:
        row = session.execute(
            text("UPDATE api_keys SET last_used_at = now() WHERE key_hash = :h AND is_active RETURNING id"),
            {"h": apikeys.digest(x_api_key.strip())},
        ).one_or_none()
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail="База данных недоступна") from exc
    if row is None:
        if not bad_key_limiter.allow(ip):
            raise HTTPException(status_code=429, detail="Слишком много запросов. Попробуйте позже.")
        raise UNAUTHORIZED
    if not key_limiter.allow(str(row.id)):
        raise HTTPException(status_code=429, detail="Превышен лимит запросов для этого ключа")
    return row.id


def _scoped(key_id: int, external_id: str) -> str:
    """Внешний номер у каждого ключа свой: два клиента с одинаковым id не пересекутся."""
    return f"k{key_id}:{external_id.strip()}"


@router.post("/appeals")
def submit(body: ExternalAppeal, key_id: int = Depends(api_key), session: Session = Depends(get_session)):
    """Приём обращения. Повтор с тем же external_id возвращает уже созданное (created=false)."""
    if not body.external_id.strip():
        raise HTTPException(status_code=422, detail="Укажите external_id")
    scoped = _scoped(key_id, body.external_id)
    data = intake.NewAppeal(
        text=body.text, source="api", address_text=body.address_text, contact_email=body.contact_email,
        district_id=body.district_id, lat=body.lat, lon=body.lon, external_id=scoped,
    )
    try:
        existed = session.execute(text("SELECT 1 FROM appeals WHERE external_id = :e"), {"e": scoped}).first()
        done = intake.register(session, data)
    except intake.IntakeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except SQLAlchemyError:
        session.rollback()
        raise HTTPException(status_code=503, detail="Не удалось сохранить обращение")
    return {"public_number": done.public_number, "external_id": body.external_id.strip(), "created": existed is None}


@router.get("/appeals/{number}")
def status(number: str, key_id: int = Depends(api_key), session: Session = Depends(get_session)):
    """Статус обращения; доступны только обращения, поданные этим же ключом."""
    number = number.strip().upper()
    if not NUMBER.match(number):
        raise HTTPException(status_code=404, detail="Обращение не найдено")
    try:
        row = session.execute(
            text(
                "SELECT a.public_number, a.external_id, a.status, a.created_at, a.due_at, a.resolved_at, "
                "a.response_text, c.name_ru AS category "
                "FROM appeals a LEFT JOIN categories c ON c.id = a.category_id "
                "WHERE a.public_number = :n AND a.external_id LIKE :p"
            ),
            {"n": number, "p": f"k{key_id}:%"},
        ).first()
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="База данных недоступна")
    if row is None:
        raise HTTPException(status_code=404, detail="Обращение не найдено")
    st = row.status or "new"
    answered = st in ("resolved", "rejected")
    return {
        "public_number": row.public_number,
        "external_id": row.external_id.split(":", 1)[1],
        "status": st,
        "status_label": STATUS_RU.get(st, st),
        "category": row.category,
        "created_at": row.created_at,
        "due_at": row.due_at,
        "resolved_at": row.resolved_at,
        "response_text": row.response_text if answered else None,
    }
