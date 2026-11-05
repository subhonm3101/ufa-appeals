"""Работа с обращением: карточка, смена статуса, назначение, комментарии (шаг 9.2)."""
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..auth import CurrentUser, client_ip, require_roles
from ..db import get_session
from ..services import workflow
from ..services.audit import log_event

router = APIRouter(prefix="/api", tags=["workflow"])

DB_DOWN = HTTPException(status_code=503, detail="База данных недоступна")
NOT_FOUND = HTTPException(status_code=404, detail="Обращение не найдено")

STAFF = ("operator", "analyst", "manager", "admin", "executor")
ASSIGNERS = ("operator", "manager", "admin")


class StatusChange(BaseModel):
    to_status: Literal["new", "accepted", "in_progress", "waiting", "resolved", "rejected"]
    comment: str | None = Field(None, max_length=2000)
    response_text: str | None = Field(None, max_length=5000)


class Assignment(BaseModel):
    department_id: int | None = None
    assignee_id: int | None = None


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    is_internal: bool = True


def _card(session: Session, appeal_id: int, user: CurrentUser) -> dict:
    row = session.execute(
        text(
            """
            SELECT a.id, a.public_number, a.external_id, a.text, a.created_at, a.status,
                   a.source, a.address_text, a.contact_email, a.lat, a.lon, a.cluster_id,
                   c.code AS category, c.name_ru AS category_name, d.name AS district,
                   a.department_id, dep.name AS department_name,
                   a.assignee_id, u.email AS assignee_email, u.full_name AS assignee_name,
                   a.due_at, a.resolved_at, a.response_text, a.updated_at
            FROM appeals a
            LEFT JOIN categories c ON c.id = a.category_id
            LEFT JOIN districts d ON d.id = a.district_id
            LEFT JOIN departments dep ON dep.id = a.department_id
            LEFT JOIN users u ON u.id = a.assignee_id
            WHERE a.id = :id
            """
        ),
        {"id": appeal_id},
    ).mappings().one_or_none()
    if row is None:
        raise NOT_FOUND
    card = dict(row)
    is_assignee = card["assignee_id"] == user.id
    if user.role == "executor" and not is_assignee:
        raise HTTPException(status_code=403, detail="Исполнитель видит только назначенные ему обращения")

    status = card["status"] or "new"
    card["status"] = status
    card["is_overdue"] = (
        card["due_at"] is not None
        and card["due_at"] < datetime.now(timezone.utc)
        and status not in workflow.CLOSED
    )
    card["allowed_transitions"] = workflow.allowed_transitions(status, user.role, is_assignee)
    card["history"] = [
        dict(r)
        for r in session.execute(
            text(
                "SELECT h.id, h.from_status, h.to_status, h.comment, h.created_at, "
                "u.email AS changed_by FROM appeal_status_history h "
                "LEFT JOIN users u ON u.id = h.changed_by "
                "WHERE h.appeal_id = :id ORDER BY h.created_at, h.id"
            ),
            {"id": appeal_id},
        ).mappings()
    ]
    card["comments"] = [
        dict(r)
        for r in session.execute(
            text(
                "SELECT m.id, m.body, m.is_internal, m.created_at, u.email AS author "
                "FROM appeal_comments m LEFT JOIN users u ON u.id = m.author_id "
                "WHERE m.appeal_id = :id ORDER BY m.created_at, m.id"
            ),
            {"id": appeal_id},
        ).mappings()
    ]
    return card


@router.get("/appeals/{appeal_id}")
def appeal_card(
    appeal_id: int,
    user: CurrentUser = Depends(require_roles(*STAFF)),
    session: Session = Depends(get_session),
):
    """Карточка обращения: поля, история статусов и комментарии."""
    try:
        return _card(session, appeal_id, user)
    except SQLAlchemyError as exc:
        raise DB_DOWN from exc


@router.post("/appeals/{appeal_id}/status")
def change_status(
    appeal_id: int,
    body: StatusChange,
    request: Request,
    user: CurrentUser = Depends(require_roles(*workflow.STATUS_CHANGERS)),
    session: Session = Depends(get_session),
):
    """Смена статуса с записью в историю и в журнал действий."""
    comment = (body.comment or "").strip() or None
    response = (body.response_text or "").strip() or None
    try:
        # блокировка строки: два сотрудника не изменят одно обращение одновременно
        row = session.execute(
            text(
                "SELECT id, status, assignee_id, created_at, due_at, response_text "
                "FROM appeals WHERE id = :id FOR UPDATE"
            ),
            {"id": appeal_id},
        ).one_or_none()
        if row is None:
            raise NOT_FOUND
        current = row.status or "new"
        problem = workflow.check_transition(
            current, body.to_status, user.role, row.assignee_id == user.id,
            comment, response or row.response_text,
        )
        if problem:
            raise HTTPException(status_code=problem[0], detail=problem[1])

        sets = ["status = :to", "updated_at = now()"]
        params: dict = {"id": appeal_id, "to": body.to_status}
        if body.to_status == "resolved":
            sets.append("resolved_at = now()")
        elif current == "resolved":
            sets.append("resolved_at = NULL")
        if body.to_status == "accepted" and row.due_at is None:
            sets.append("due_at = :due")
            params["due"] = workflow.due_date(row.created_at)
        if response:
            sets.append("response_text = :resp")
            params["resp"] = response
        session.execute(text(f"UPDATE appeals SET {', '.join(sets)} WHERE id = :id"), params)
        session.execute(
            text(
                "INSERT INTO appeal_status_history (appeal_id, from_status, to_status, changed_by, comment) "
                "VALUES (:id, :frm, :to, :by, :c)"
            ),
            {"id": appeal_id, "frm": current, "to": body.to_status, "by": user.id, "c": comment},
        )
        log_event(
            session, user.id, "appeal_status_changed", "appeal", appeal_id,
            details={"from": current, "to": body.to_status}, ip=client_ip(request),
        )
        return _card(session, appeal_id, user)
    except SQLAlchemyError as exc:
        session.rollback()
        raise DB_DOWN from exc


@router.post("/appeals/{appeal_id}/assign")
def assign(
    appeal_id: int,
    body: Assignment,
    request: Request,
    user: CurrentUser = Depends(require_roles(*ASSIGNERS)),
    session: Session = Depends(get_session),
):
    """Назначить подразделение и/или исполнителя. null снимает назначение."""
    given = body.model_fields_set & {"department_id", "assignee_id"}
    if not given:
        raise HTTPException(status_code=422, detail="Укажите подразделение или исполнителя")
    try:
        row = session.execute(
            text("SELECT id, status, department_id, assignee_id FROM appeals WHERE id = :id FOR UPDATE"),
            {"id": appeal_id},
        ).one_or_none()
        if row is None:
            raise NOT_FOUND
        if (row.status or "new") in workflow.CLOSED:
            raise HTTPException(
                status_code=409, detail="Закрытое обращение нельзя назначать: сначала возобновите его"
            )

        department_id = body.department_id if "department_id" in given else row.department_id
        assignee_id = body.assignee_id if "assignee_id" in given else row.assignee_id

        assignee = None
        if assignee_id is not None:
            assignee = session.execute(
                text(
                    "SELECT id, email, full_name, department_id FROM users "
                    "WHERE id = :id AND is_active AND role = 'executor'"
                ),
                {"id": assignee_id},
            ).one_or_none()
            if assignee is None:
                raise HTTPException(
                    status_code=422,
                    detail="Исполнитель не найден: нужен активный пользователь с ролью «Исполнитель»",
                )
            # при назначении исполнителя подразделение берётся из его карточки
            if "department_id" not in given and assignee.department_id is not None:
                department_id = assignee.department_id

        department_name = None
        if department_id is not None:
            department_name = session.execute(
                text("SELECT name FROM departments WHERE id = :id AND is_active"), {"id": department_id}
            ).scalar_one_or_none()
            if department_name is None:
                raise HTTPException(status_code=422, detail="Подразделение не найдено или отключено")
        if assignee is not None and assignee.department_id not in (None, department_id):
            raise HTTPException(
                status_code=422,
                detail="Исполнитель относится к другому подразделению: замените или снимите исполнителя",
            )
        if department_id == row.department_id and assignee_id == row.assignee_id:
            raise HTTPException(status_code=409, detail="Назначение не изменилось")

        session.execute(
            text(
                "UPDATE appeals SET department_id = :d, assignee_id = :a, updated_at = now() WHERE id = :id"
            ),
            {"d": department_id, "a": assignee_id, "id": appeal_id},
        )
        who = (assignee.full_name or assignee.email) if assignee else "не назначен"
        session.execute(
            text(
                "INSERT INTO appeal_comments (appeal_id, author_id, body, is_internal) "
                "VALUES (:id, :by, :body, TRUE)"
            ),
            {
                "id": appeal_id, "by": user.id,
                "body": f"Назначено: подразделение — {department_name or 'не указано'}; исполнитель — {who}",
            },
        )
        log_event(
            session, user.id, "appeal_assigned", "appeal", appeal_id,
            details={"department_id": department_id, "assignee_id": assignee_id}, ip=client_ip(request),
        )
        return _card(session, appeal_id, user)
    except SQLAlchemyError as exc:
        session.rollback()
        raise DB_DOWN from exc


@router.post("/appeals/{appeal_id}/comments", status_code=201)
def add_comment(
    appeal_id: int,
    body: CommentIn,
    request: Request,
    user: CurrentUser = Depends(require_roles(*workflow.STATUS_CHANGERS)),
    session: Session = Depends(get_session),
):
    """Комментарий сотрудника: внутренний (по умолчанию) или публичный."""
    text_body = body.body.strip()
    if not text_body:
        raise HTTPException(status_code=422, detail="Комментарий не может быть пустым")
    try:
        assignee_id = session.execute(
            text("SELECT assignee_id FROM appeals WHERE id = :id"), {"id": appeal_id}
        ).one_or_none()
        if assignee_id is None:
            raise NOT_FOUND
        if user.role == "executor" and assignee_id[0] != user.id:
            raise HTTPException(
                status_code=403, detail="Исполнитель может комментировать только назначенные ему обращения"
            )
        comment = session.execute(
            text(
                "INSERT INTO appeal_comments (appeal_id, author_id, body, is_internal) "
                "VALUES (:id, :by, :body, :internal) RETURNING id, body, is_internal, created_at"
            ),
            {"id": appeal_id, "by": user.id, "body": text_body, "internal": body.is_internal},
        ).mappings().one()
        session.execute(text("UPDATE appeals SET updated_at = now() WHERE id = :id"), {"id": appeal_id})
        log_event(
            session, user.id, "appeal_commented", "appeal", appeal_id,
            details={"internal": body.is_internal}, ip=client_ip(request),
        )
    except SQLAlchemyError as exc:
        session.rollback()
        raise DB_DOWN from exc
    return {**comment, "author": user.email}


@router.get("/executors")
def list_executors(
    department_id: int | None = Query(None),
    user: CurrentUser = Depends(require_roles(*ASSIGNERS)),
    session: Session = Depends(get_session),
):
    """Активные исполнители (для выбора при назначении)."""
    where, params = "WHERE role = 'executor' AND is_active", {}
    if department_id is not None:
        where += " AND department_id = :d"
        params["d"] = department_id
    try:
        rows = session.execute(
            text(f"SELECT id, email, full_name, department_id FROM users {where} ORDER BY full_name NULLS LAST, email"),
            params,
        ).mappings().all()
    except SQLAlchemyError as exc:
        raise DB_DOWN from exc
    return [dict(r) for r in rows]
