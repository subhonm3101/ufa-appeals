"""Личный кабинет гражданина: свои обращения, публичная переписка, дополнения."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..auth import CurrentUser, client_ip, require_roles
from ..db import get_session
from ..services import notifications
from ..services.audit import log_event
from ..services.ratelimit import DbRateLimiter
from .public import NUMBER, STATUS_RU

router = APIRouter(prefix="/api/my", tags=["citizen"])

comment_limiter = DbRateLimiter("citizen_comment", limit=20, window=3600)

CLOSED = ("resolved", "rejected")
NOT_FOUND = HTTPException(status_code=404, detail="Обращение не найдено")
DB_DOWN = HTTPException(status_code=503, detail="База данных недоступна")


class CitizenComment(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


def _own(session: Session, number: str, user_id: int):
    number = number.strip().upper()
    if not NUMBER.match(number):
        raise NOT_FOUND
    row = session.execute(
        text(
            "SELECT a.id, a.public_number, COALESCE(a.status, 'new') AS status, a.text, a.address_text, "
            "a.created_at, a.due_at, a.resolved_at, a.response_text, "
            "c.name_ru AS category, d.name AS district "
            "FROM appeals a LEFT JOIN categories c ON c.id = a.category_id "
            "LEFT JOIN districts d ON d.id = a.district_id "
            "WHERE a.public_number = :n AND a.citizen_id = :u"
        ),
        {"n": number, "u": user_id},
    ).one_or_none()
    if row is None:
        raise NOT_FOUND
    return row


def _detail(session: Session, number: str, user_id: int) -> dict:
    a = _own(session, number, user_id)
    answered = a.status in CLOSED
    reason = None
    if a.status == "rejected":
        reason = session.execute(
            text(
                "SELECT comment FROM appeal_status_history "
                "WHERE appeal_id = :i AND to_status = 'rejected' ORDER BY created_at DESC, id DESC LIMIT 1"
            ),
            {"i": a.id},
        ).scalar_one_or_none()
    history = session.execute(
        text("SELECT to_status, created_at FROM appeal_status_history WHERE appeal_id = :i ORDER BY created_at, id"),
        {"i": a.id},
    ).all()
    messages = session.execute(
        text(
            "SELECT body, created_at, (author_id = :u) AS mine FROM appeal_comments "
            "WHERE appeal_id = :i AND NOT is_internal ORDER BY created_at, id"
        ),
        {"i": a.id, "u": user_id},
    ).all()
    return {
        "public_number": a.public_number,
        "status": a.status,
        "status_label": STATUS_RU.get(a.status, a.status),
        "text": a.text,
        "address_text": a.address_text,
        "category": a.category,
        "district": a.district,
        "created_at": a.created_at,
        "due_at": a.due_at,
        "resolved_at": a.resolved_at,
        "response_text": a.response_text if answered else None,
        "reject_reason": reason,
        "can_comment": not answered,
        "history": [
            {"status": h.to_status, "status_label": STATUS_RU.get(h.to_status, h.to_status), "at": h.created_at}
            for h in history
        ],
        "messages": [{"body": m.body, "at": m.created_at, "mine": bool(m.mine)} for m in messages],
    }


@router.get("/appeals")
def my_appeals(
    user: CurrentUser = Depends(require_roles("citizen")),
    session: Session = Depends(get_session),
):
    """Обращения, поданные этим гражданином, новые сверху."""
    try:
        rows = session.execute(
            text(
                "SELECT a.public_number, COALESCE(a.status, 'new') AS status, a.created_at, a.due_at, "
                "left(a.text, 200) AS excerpt, c.name_ru AS category "
                "FROM appeals a LEFT JOIN categories c ON c.id = a.category_id "
                "WHERE a.citizen_id = :u ORDER BY a.created_at DESC, a.id DESC LIMIT 200"
            ),
            {"u": user.id},
        ).all()
    except SQLAlchemyError:
        raise DB_DOWN
    return [
        {
            "public_number": r.public_number,
            "status": r.status,
            "status_label": STATUS_RU.get(r.status, r.status),
            "category": r.category,
            "created_at": r.created_at,
            "due_at": r.due_at,
            "excerpt": r.excerpt,
        }
        for r in rows
    ]


@router.get("/appeals/{number}")
def my_appeal(
    number: str,
    user: CurrentUser = Depends(require_roles("citizen")),
    session: Session = Depends(get_session),
):
    """Своё обращение: статусы, ответ и публичная переписка. Внутренние заметки не показываются."""
    try:
        return _detail(session, number, user.id)
    except SQLAlchemyError:
        raise DB_DOWN


@router.post("/appeals/{number}/comments", status_code=201)
def add_comment(
    number: str,
    body: CitizenComment,
    request: Request,
    user: CurrentUser = Depends(require_roles("citizen")),
    session: Session = Depends(get_session),
):
    """Дополнение к обращению от гражданина; сотрудники видят его в карточке как публичное."""
    if not comment_limiter.allow(str(user.id)):
        raise HTTPException(status_code=429, detail="Слишком много сообщений. Попробуйте позже.")
    text_body = body.body.strip()
    if not text_body:
        raise HTTPException(status_code=422, detail="Сообщение не должно быть пустым")
    try:
        a = _own(session, number, user.id)
        if a.status in CLOSED:
            raise HTTPException(status_code=409, detail="Обращение закрыто: дополнить его нельзя")
        session.execute(
            text(
                "INSERT INTO appeal_comments (appeal_id, author_id, body, is_internal) "
                "VALUES (:i, :u, :b, FALSE)"
            ),
            {"i": a.id, "u": user.id, "b": text_body},
        )
        session.execute(text("UPDATE appeals SET updated_at = now() WHERE id = :i"), {"i": a.id})
        recipients = session.execute(
            text(
                "SELECT assignee_id AS id FROM appeals WHERE id = :i AND assignee_id IS NOT NULL "
                "UNION SELECT id FROM users WHERE is_active AND role IN ('operator', 'manager') "
                "AND NOT EXISTS (SELECT 1 FROM appeals WHERE id = :i AND assignee_id IS NOT NULL)"
            ),
            {"i": a.id},
        ).scalars().all()
        for rid in recipients:
            notifications.notify(
                session, rid, a.id, "citizen_comment",
                f"Гражданин дополнил обращение {a.public_number}",
            )
        log_event(session, user.id, "citizen_comment_added", "appeal", a.id, ip=client_ip(request))
        return _detail(session, number, user.id)
    except SQLAlchemyError:
        session.rollback()
        raise DB_DOWN
