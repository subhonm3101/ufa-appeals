"""Публичный приём обращений и проверка статуса по номеру (без входа в систему)."""
import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..auth import client_ip, oauth2_scheme
from ..db import get_session
from ..services import attachments, intake
from ..services.ratelimit import RateLimiter
from ..services.security import decode_access_claims

router = APIRouter(prefix="/api/public", tags=["public"])

submit_limiter = RateLimiter(limit=5, window=3600)
lookup_limiter = RateLimiter(limit=60, window=600)

NUMBER = re.compile(r"^UFA-\d{4}-\d{6}$")
STATUS_RU = {
    "new": "Зарегистрировано",
    "accepted": "Принято в работу",
    "in_progress": "Выполняется",
    "waiting": "Ожидает уточнения",
    "resolved": "Решено",
    "rejected": "Отклонено",
}
TOO_MANY = HTTPException(status_code=429, detail="Слишком много запросов. Попробуйте позже.")


def optional_citizen(
    token: str | None = Depends(oauth2_scheme), session: Session = Depends(get_session)
):
    """Гражданин по токену, если он вошёл; иначе None: подавать обращение можно и без входа."""
    if not token:
        return None
    claims = decode_access_claims(token)
    if claims is None:
        return None
    user_id, version = claims
    try:
        return session.execute(
            text("SELECT id, email FROM users WHERE id = :i AND is_active AND role = 'citizen' "
            "AND token_version = :v"),
            {"i": user_id, "v": version},
        ).one_or_none()
    except SQLAlchemyError:
        return None


@router.get("/districts")
def districts(session: Session = Depends(get_session)):
    try:
        rows = session.execute(text("SELECT id, name FROM districts ORDER BY name")).all()
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="База данных недоступна")
    return [{"id": r.id, "name": r.name} for r in rows]


@router.post("/appeals", status_code=201)
def submit(
    request: Request,
    body_text: str = Form(alias="text", max_length=6000),
    address_text: str | None = Form(None, max_length=400),
    contact_email: str | None = Form(None, max_length=300),
    district_id: int | None = Form(None),
    files: list[UploadFile] = File(default=[]),
    session: Session = Depends(get_session),
    citizen=Depends(optional_citizen),
):
    """Приём обращения: поля формы и до трёх фотографий (multipart/form-data)."""
    if not submit_limiter.allow(client_ip(request)):
        raise TOO_MANY
    data = intake.NewAppeal(
        text=body_text,
        source="web",
        address_text=address_text,
        contact_email=contact_email or (citizen.email if citizen else None),
        district_id=district_id,
        citizen_id=citizen.id if citizen else None,
    )
    try:
        intake.clean(data)
        raw = [(f.filename, f.file.read(attachments.MAX_SIZE + 1)) for f in files if f.filename]
        checked = attachments.check_files(raw)
        done = intake.register(session, data)
        attachments.save(session, done.id, checked)
    except intake.IntakeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except (SQLAlchemyError, OSError):
        session.rollback()
        raise HTTPException(status_code=503, detail="Не удалось сохранить обращение")
    return {"public_number": done.public_number}


@router.get("/appeals/{number}")
def status_by_number(number: str, request: Request, session: Session = Depends(get_session)):
    if not lookup_limiter.allow(client_ip(request)):
        raise TOO_MANY
    number = number.strip().upper()
    if not NUMBER.match(number):
        raise HTTPException(status_code=404, detail="Обращение с таким номером не найдено")
    try:
        row = session.execute(
            text(
                "SELECT a.public_number, a.status, a.created_at, a.due_at, a.resolved_at, "
                "a.response_text, c.name_ru AS category "
                "FROM appeals a LEFT JOIN categories c ON c.id = a.category_id "
                "WHERE a.public_number = :n"
            ),
            {"n": number},
        ).first()
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="База данных недоступна")
    if not row:
        raise HTTPException(status_code=404, detail="Обращение с таким номером не найдено")
    status = row.status or "new"
    answered = status in ("resolved", "rejected")
    return {
        "public_number": row.public_number,
        "status": status,
        "status_label": STATUS_RU.get(status, status),
        "category": row.category,
        "created_at": row.created_at,
        "due_at": row.due_at,
        "resolved_at": row.resolved_at,
        "response_text": row.response_text if answered else None,
    }
