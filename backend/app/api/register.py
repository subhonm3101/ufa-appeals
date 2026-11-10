"""Регистрация гражданина: учётная запись с ролью «гражданин» и сразу выданный токен."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from ..auth import client_ip
from ..db import get_session
from ..schemas import Token, UserOut
from ..services.audit import log_event
from ..services.ratelimit import RateLimiter
from ..services.security import (
    check_password_strength, create_access_token, hash_password, normalize_email,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

register_limiter = RateLimiter(limit=5, window=3600)

DUPLICATE = HTTPException(status_code=409, detail="Эта почта уже зарегистрирована. Войдите в систему.")


class RegisterIn(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)
    full_name: str | None = Field(None, max_length=200)


@router.post("/register", response_model=Token, status_code=201)
def register(body: RegisterIn, request: Request, session: Session = Depends(get_session)):
    """Регистрация гражданина по почте и паролю; после неё вход выполнен сразу."""
    ip = client_ip(request)
    if not register_limiter.allow(ip or "unknown"):
        raise HTTPException(status_code=429, detail="Слишком много регистраций. Попробуйте позже.")
    try:
        email = normalize_email(body.email)
    except ValueError:
        raise HTTPException(status_code=422, detail="Укажите корректный адрес электронной почты")
    error = check_password_strength(body.password, email)
    if error:
        raise HTTPException(status_code=422, detail=error)
    name = " ".join((body.full_name or "").split()) or None
    try:
        if session.execute(text("SELECT 1 FROM users WHERE lower(email) = :e"), {"e": email}).first():
            raise DUPLICATE
        row = session.execute(
            text(
                "INSERT INTO users (email, full_name, role, password_hash, is_active, last_login_at) "
                "VALUES (:e, :n, 'citizen', :h, TRUE, now()) RETURNING id, created_at, last_login_at"
            ),
            {"e": email, "n": name, "h": hash_password(body.password)},
        ).one()
        log_event(session, row.id, "citizen_registered", "user", row.id, ip=ip)
    except IntegrityError:
        session.rollback()
        raise DUPLICATE
    except SQLAlchemyError:
        session.rollback()
        raise HTTPException(status_code=503, detail="База данных недоступна")
    token, expires_in = create_access_token(row.id, "citizen")
    return Token(
        access_token=token,
        expires_in=expires_in,
        user=UserOut(
            id=row.id, email=email, full_name=name, role="citizen", is_active=True,
            last_login_at=row.last_login_at, created_at=row.created_at,
        ),
    )
