"""Просмотр вложений обращения сотрудниками."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..auth import CurrentUser, require_roles
from ..db import get_session
from ..services import attachments

router = APIRouter(prefix="/api", tags=["attachments"])

STAFF = ("operator", "analyst", "manager", "admin", "executor")
NOT_FOUND = HTTPException(status_code=404, detail="Вложение не найдено")


def _allowed(session: Session, appeal_id: int, user: CurrentUser) -> bool:
    row = session.execute(
        text("SELECT assignee_id FROM appeals WHERE id = :i"), {"i": appeal_id}
    ).first()
    if not row:
        return False
    return user.role != "executor" or row.assignee_id == user.id


@router.get("/appeals/{appeal_id}/attachments")
def list_attachments(
    appeal_id: int,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(require_roles(*STAFF)),
):
    try:
        if not _allowed(session, appeal_id, user):
            raise HTTPException(status_code=404, detail="Обращение не найдено")
        rows = session.execute(
            text(
                "SELECT id, original_name, content_type, size_bytes, created_at "
                "FROM appeal_attachments WHERE appeal_id = :i ORDER BY id"
            ),
            {"i": appeal_id},
        ).all()
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="База данных недоступна")
    return [
        {
            "id": r.id,
            "name": r.original_name,
            "content_type": r.content_type,
            "size_bytes": r.size_bytes,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.get("/attachments/{attachment_id}/file")
def get_file(
    attachment_id: int,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(require_roles(*STAFF)),
):
    try:
        row = session.execute(
            text(
                "SELECT appeal_id, content_type, storage_name FROM appeal_attachments WHERE id = :i"
            ),
            {"i": attachment_id},
        ).first()
        if not row or not _allowed(session, row.appeal_id, user):
            raise NOT_FOUND
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="База данных недоступна")
    path = attachments.UPLOAD_DIR / row.storage_name
    if not path.is_file():
        raise NOT_FOUND
    return FileResponse(
        path,
        media_type=row.content_type,
        headers={"Content-Disposition": "inline", "X-Content-Type-Options": "nosniff"},
    )
