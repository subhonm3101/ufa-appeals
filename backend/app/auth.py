"""Текущий пользователь и проверка ролей."""
from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .db import get_session
from .services.security import decode_access_token

ROLES = ("operator", "analyst", "manager", "admin", "executor")

# auto_error=False: сообщение об отсутствии токена формируем сами, по-русски
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


class CurrentUser(BaseModel):
    id: int
    email: str
    full_name: str | None = None
    role: str


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=401, detail="Требуется вход в систему", headers={"WWW-Authenticate": "Bearer"})


def get_current_user(
    token: str | None = Depends(oauth2_scheme), session: Session = Depends(get_session)
) -> CurrentUser:
    """Пользователь по токену. Роль и активность берутся из базы при каждом запросе,
    поэтому отключение или смена роли действуют сразу, а не после истечения токена."""
    if not token:
        raise _unauthorized()
    user_id = decode_access_token(token)
    if user_id is None:
        raise _unauthorized()
    try:
        row = session.execute(
            text("SELECT id, email, full_name, role, is_active FROM users WHERE id = :id"), {"id": user_id}
        ).one_or_none()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="База данных недоступна") from exc
    if row is None or not row.is_active:
        raise _unauthorized()
    return CurrentUser(id=row.id, email=row.email, full_name=row.full_name, role=row.role)


def require_roles(*roles: str):
    """Зависимость: пускает только перечисленные роли."""
    unknown = set(roles) - set(ROLES)
    assert not unknown, f"неизвестные роли: {unknown}"

    def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Недостаточно прав для этого действия")
        return user

    return checker


def client_ip(request: Request) -> str | None:
    """Адрес клиента. Заголовку X-Forwarded-For не доверяем: его может подставить кто угодно."""
    return request.client.host if request.client else None
