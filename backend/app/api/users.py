"""Управление пользователями и просмотр журнала действий (только администратор)."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from ..auth import CurrentUser, client_ip, require_roles
from ..db import get_session
from ..schemas import AuditEntry, AuditPage, UserCreate, UserOut, UserUpdate
from ..services.audit import log_event
from ..services.security import check_password_strength, hash_password, normalize_email

router = APIRouter(prefix="/api", tags=["admin"])

DB_DOWN = HTTPException(status_code=503, detail="База данных недоступна")
USER_COLS = "id, email, full_name, role, is_active, last_login_at, created_at"


@router.get("/users", response_model=list[UserOut])
def list_users(admin: CurrentUser = Depends(require_roles("admin")), session: Session = Depends(get_session)):
    try:
        rows = session.execute(text(f"SELECT {USER_COLS} FROM users ORDER BY id")).mappings().all()
    except SQLAlchemyError as exc:
        raise DB_DOWN from exc
    return [UserOut(**r) for r in rows]


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(
    body: UserCreate, request: Request,
    admin: CurrentUser = Depends(require_roles("admin")), session: Session = Depends(get_session),
):
    try:
        email = normalize_email(body.email)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    error = check_password_strength(body.password, email)
    if error:
        raise HTTPException(status_code=422, detail=error)
    try:
        if session.execute(text("SELECT 1 FROM users WHERE lower(email) = :e"), {"e": email}).first():
            raise HTTPException(status_code=409, detail="Пользователь с таким email уже существует")
        row = session.execute(
            text(
                "INSERT INTO users (email, password_hash, full_name, role) VALUES (:e, :h, :n, :r) "
                f"RETURNING {USER_COLS}"
            ),
            {"e": email, "h": hash_password(body.password), "n": (body.full_name or "").strip() or None, "r": body.role},
        ).mappings().one()
        log_event(session, admin.id, "user_created", "user", row["id"],
                  details={"email": email, "role": body.role}, ip=client_ip(request))
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Пользователь с таким email уже существует") from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise DB_DOWN from exc
    return UserOut(**row)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int, body: UserUpdate, request: Request,
    admin: CurrentUser = Depends(require_roles("admin")), session: Session = Depends(get_session),
):
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Не указано, что менять")
    if user_id == admin.id and (changes.get("role", "admin") != "admin" or changes.get("is_active", True) is False):
        raise HTTPException(
            status_code=409, detail="Нельзя понизить или отключить собственную учётную запись (иначе некому будет управлять системой)"
        )
    sets, params, logged = [], {"id": user_id}, {}
    if "role" in changes and changes["role"] is not None:
        sets.append("role = :role"); params["role"] = changes["role"]; logged["role"] = changes["role"]
    if "full_name" in changes:
        sets.append("full_name = :name"); params["name"] = (changes["full_name"] or "").strip() or None
        logged["full_name"] = params["name"]
    if "is_active" in changes and changes["is_active"] is not None:
        sets.append("is_active = :active"); params["active"] = changes["is_active"]; logged["is_active"] = changes["is_active"]
    if changes.get("password") is not None:
        try:
            target_email = session.execute(text("SELECT email FROM users WHERE id = :id"), {"id": user_id}).scalar()
        except SQLAlchemyError as exc:
            raise DB_DOWN from exc
        error = check_password_strength(changes["password"], target_email)
        if error:
            raise HTTPException(status_code=422, detail=error)
        sets.append("password_hash = :h"); params["h"] = hash_password(changes["password"]); logged["password_reset"] = True
    if not sets:
        raise HTTPException(status_code=422, detail="Не указано, что менять")
    try:
        row = session.execute(
            text(f"UPDATE users SET {', '.join(sets)} WHERE id = :id RETURNING {USER_COLS}"), params
        ).mappings().one_or_none()
        if row is None:
            session.rollback()
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        log_event(session, admin.id, "user_updated", "user", user_id, details=logged, ip=client_ip(request))
    except SQLAlchemyError as exc:
        session.rollback()
        raise DB_DOWN from exc
    return UserOut(**row)


@router.get("/audit", response_model=AuditPage)
def list_audit(
    user_id: int | None = None,
    action: str | None = Query(None, max_length=50),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: CurrentUser = Depends(require_roles("admin")),
    session: Session = Depends(get_session),
):
    """Журнал действий: входы, неудачные попытки, импорт, управление пользователями. Свежие первыми."""
    where, params = "WHERE TRUE", {}
    if user_id is not None:
        where += " AND l.user_id = :user_id"; params["user_id"] = user_id
    if action:
        where += " AND l.action = :action"; params["action"] = action
    base = f"FROM audit_log l LEFT JOIN users u ON u.id = l.user_id {where}"
    try:
        total = session.execute(text("SELECT COUNT(*) " + base), params).scalar_one()
        rows = session.execute(
            text(
                "SELECT l.id, l.created_at, l.user_id, u.email AS user_email, l.action, l.entity, "
                "l.entity_id, l.details, l.ip " + base + " ORDER BY l.created_at DESC, l.id DESC LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": limit, "offset": offset},
        ).mappings().all()
    except SQLAlchemyError as exc:
        raise DB_DOWN from exc
    return AuditPage(total=total, limit=limit, offset=offset, items=[AuditEntry(**r) for r in rows])
