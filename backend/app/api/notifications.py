"""Уведомления текущего пользователя (шаг 9.5)."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..auth import CurrentUser, require_roles
from ..db import get_session
from ..services.notifications import refresh_deadlines

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

DB_DOWN = HTTPException(status_code=503, detail="База данных недоступна")
STAFF = ("operator", "analyst", "manager", "admin", "executor", "citizen")


def _unread(session: Session, user_id: int) -> int:
    return session.execute(
        text("SELECT count(*) FROM notifications WHERE user_id = :u AND read_at IS NULL"), {"u": user_id}
    ).scalar_one()


@router.get("")
def list_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(require_roles(*STAFF)),
    session: Session = Depends(get_session),
):
    """Уведомления пользователя, новые сверху. Заодно проверяются сроки."""
    where = "WHERE user_id = :u" + (" AND read_at IS NULL" if unread_only else "")
    try:
        if user.role != "citizen":
            refresh_deadlines(session, user.id, user.role)
        total = session.execute(text(f"SELECT count(*) FROM notifications {where}"), {"u": user.id}).scalar_one()
        rows = session.execute(
            text(
                "SELECT id, appeal_id, kind, message, created_at, read_at FROM notifications "
                f"{where} ORDER BY created_at DESC, id DESC LIMIT :limit OFFSET :offset"
            ),
            {"u": user.id, "limit": limit, "offset": offset},
        ).mappings().all()
        unread = _unread(session, user.id)
    except SQLAlchemyError as exc:
        session.rollback()
        raise DB_DOWN from exc
    return {"total": total, "unread": unread, "items": [dict(r) for r in rows]}


@router.get("/unread-count")
def unread_count(
    user: CurrentUser = Depends(require_roles(*STAFF)),
    session: Session = Depends(get_session),
):
    """Число непрочитанных (для значка у колокольчика)."""
    try:
        if user.role != "citizen":
            refresh_deadlines(session, user.id, user.role)
        return {"unread": _unread(session, user.id)}
    except SQLAlchemyError as exc:
        session.rollback()
        raise DB_DOWN from exc


@router.post("/read-all")
def read_all(
    user: CurrentUser = Depends(require_roles(*STAFF)),
    session: Session = Depends(get_session),
):
    try:
        done = session.execute(
            text("UPDATE notifications SET read_at = now() WHERE user_id = :u AND read_at IS NULL"),
            {"u": user.id},
        ).rowcount
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        raise DB_DOWN from exc
    return {"marked": done}


@router.post("/{notification_id}/read")
def mark_read(
    notification_id: int,
    user: CurrentUser = Depends(require_roles(*STAFF)),
    session: Session = Depends(get_session),
):
    """Отметить прочитанным. Чужое уведомление «не найдено»."""
    try:
        row = session.execute(
            text(
                "UPDATE notifications SET read_at = COALESCE(read_at, now()) "
                "WHERE id = :id AND user_id = :u RETURNING id"
            ),
            {"id": notification_id, "u": user.id},
        ).one_or_none()
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        raise DB_DOWN from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Уведомление не найдено")
    return {"id": row.id}
