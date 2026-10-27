from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..auth import CurrentUser, client_ip, get_current_user
from ..config import settings
from ..db import get_session
from ..schemas import PasswordChange, Token, UserOut
from ..services.audit import log_event
from ..services.security import (
    check_password_strength, create_access_token, dummy_hash, hash_password, verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

DB_DOWN = HTTPException(status_code=503, detail="База данных недоступна")


def _is_locked(session: Session, email: str) -> bool:
    """Заблокирован ли вход для этого email: слишком много неудач после последнего успешного входа."""
    failures = session.execute(
        text(
            """
            SELECT COUNT(*) FROM audit_log
            WHERE action = 'login_failed' AND details->>'email' = :e
              AND created_at > GREATEST(
                    now() - (:m * interval '1 minute'),
                    COALESCE((SELECT MAX(created_at) FROM audit_log
                              WHERE action = 'login' AND details->>'email' = :e),
                             CAST('-infinity' AS timestamptz)))
            """
        ),
        {"e": email, "m": settings.lockout_minutes},
    ).scalar_one()
    return failures >= settings.max_failed_logins


@router.post("/login", response_model=Token)
def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), session: Session = Depends(get_session)):
    """Вход по email и паролю (в форме поле называется username). Возвращает токен для заголовка
    Authorization: Bearer <токен>."""
    email = form.username.strip().lower()[:200]
    ip = client_ip(request)
    try:
        if _is_locked(session, email):
            raise HTTPException(
                status_code=429,
                detail=f"Слишком много неудачных попыток входа. Повторите через {settings.lockout_minutes} мин.",
            )
        row = session.execute(
            text(
                "SELECT id, email, full_name, role, password_hash, is_active, created_at "
                "FROM users WHERE lower(email) = :e"
            ),
            {"e": email},
        ).one_or_none()
        # Пароль проверяем всегда (для неизвестного email против «пустышки»): время ответа не выдаёт, есть ли такой email
        ok = verify_password(form.password, row.password_hash if row else dummy_hash())
        if row is None or not ok:
            log_event(session, None, "login_failed", details={"email": email}, ip=ip)
            raise HTTPException(
                status_code=401, detail="Неверный email или пароль", headers={"WWW-Authenticate": "Bearer"}
            )
        if not row.is_active:
            log_event(session, row.id, "login_blocked", details={"email": email, "reason": "inactive"}, ip=ip)
            raise HTTPException(status_code=403, detail="Учётная запись отключена")
        last_login = session.execute(
            text("UPDATE users SET last_login_at = now() WHERE id = :id RETURNING last_login_at"), {"id": row.id}
        ).scalar_one()
        log_event(session, row.id, "login", details={"email": email}, ip=ip)
    except SQLAlchemyError as exc:
        session.rollback()
        raise DB_DOWN from exc

    token, expires_in = create_access_token(row.id, row.role)
    return Token(
        access_token=token, expires_in=expires_in,
        user=UserOut(id=row.id, email=row.email, full_name=row.full_name, role=row.role,
                     is_active=True, last_login_at=last_login, created_at=row.created_at),
    )


@router.get("/me", response_model=CurrentUser)
def me(user: CurrentUser = Depends(get_current_user)):
    """Кто я: проверка токена и роли."""
    return user


@router.post("/change-password", status_code=204)
def change_password(
    body: PasswordChange, request: Request,
    user: CurrentUser = Depends(get_current_user), session: Session = Depends(get_session),
):
    try:
        stored = session.execute(
            text("SELECT password_hash FROM users WHERE id = :id"), {"id": user.id}
        ).scalar_one()
        if not verify_password(body.current_password, stored):
            raise HTTPException(status_code=400, detail="Текущий пароль указан неверно")
        error = check_password_strength(body.new_password, user.email)
        if error:
            raise HTTPException(status_code=422, detail=error)
        session.execute(
            text("UPDATE users SET password_hash = :h WHERE id = :id"),
            {"h": hash_password(body.new_password), "id": user.id},
        )
        log_event(session, user.id, "password_changed", "user", user.id, ip=client_ip(request))
    except SQLAlchemyError as exc:
        session.rollback()
        raise DB_DOWN from exc
