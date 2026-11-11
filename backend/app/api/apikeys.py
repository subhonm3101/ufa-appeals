"""Управление ключами внешнего API (только администратор)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..auth import CurrentUser, client_ip, require_roles
from ..db import get_session
from ..services import apikeys
from ..services.audit import log_event

router = APIRouter(prefix="/api/api-keys", tags=["api-keys"])

DB_DOWN = HTTPException(status_code=503, detail="База данных недоступна")


class KeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


@router.get("")
def list_keys(
    user: CurrentUser = Depends(require_roles("admin")),
    session: Session = Depends(get_session),
):
    try:
        rows = session.execute(
            text(
                "SELECT id, name, prefix, is_active, created_at, last_used_at, revoked_at "
                "FROM api_keys ORDER BY id DESC"
            )
        ).mappings().all()
    except SQLAlchemyError as exc:
        session.rollback()
        raise DB_DOWN from exc
    return [dict(r) for r in rows]


@router.post("", status_code=201)
def create_key(
    body: KeyIn,
    request: Request,
    user: CurrentUser = Depends(require_roles("admin")),
    session: Session = Depends(get_session),
):
    """Выпускает ключ. Сам ключ возвращается только в этом ответе."""
    name = " ".join(body.name.split())
    if not name:
        raise HTTPException(status_code=422, detail="Укажите название ключа")
    key = apikeys.generate()
    try:
        row = session.execute(
            text(
                "INSERT INTO api_keys (name, prefix, key_hash, created_by) "
                "VALUES (:n, :p, :h, :u) RETURNING id"
            ),
            {"n": name, "p": apikeys.shown_prefix(key), "h": apikeys.digest(key), "u": user.id},
        ).one()
        log_event(session, user.id, "api_key_created", "api_key", row.id, details={"name": name}, ip=client_ip(request))
    except SQLAlchemyError as exc:
        session.rollback()
        raise DB_DOWN from exc
    return {"id": row.id, "name": name, "key": key}


@router.post("/{key_id}/revoke")
def revoke_key(
    key_id: int,
    request: Request,
    user: CurrentUser = Depends(require_roles("admin")),
    session: Session = Depends(get_session),
):
    try:
        row = session.execute(
            text(
                "UPDATE api_keys SET is_active = FALSE, revoked_at = COALESCE(revoked_at, now()) "
                "WHERE id = :i RETURNING id"
            ),
            {"i": key_id},
        ).one_or_none()
        if row is None:
            session.rollback()
            raise HTTPException(status_code=404, detail="Ключ не найден")
        log_event(session, user.id, "api_key_revoked", "api_key", key_id, ip=client_ip(request))
    except SQLAlchemyError as exc:
        session.rollback()
        raise DB_DOWN from exc
    return {"id": key_id, "is_active": False}
