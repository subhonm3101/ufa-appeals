"""Пароли (scrypt из стандартной библиотеки) и токены доступа (JWT)."""
import base64
import functools
import hashlib
import hmac
import os
import re
from datetime import datetime, timedelta, timezone

import jwt

from ..config import settings

# Параметры scrypt (память ~32 МБ на хеш). Хранятся в самой строке хеша, их можно усилить позже.
_N, _R, _P = 2**15, 8, 1
_MAXMEM = 64 * 1024 * 1024
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _unb64(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"), validate=True)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, maxmem=_MAXMEM, dklen=32)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, dk = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = _unb64(dk)
        calc = hashlib.scrypt(
            password.encode("utf-8"), salt=_unb64(salt), n=int(n), r=int(r), p=int(p),
            maxmem=_MAXMEM, dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(calc, expected)


@functools.cache
def dummy_hash() -> str:
    """Хеш для проверки пароля несуществующего пользователя (чтобы время ответа не выдавало, есть ли email)."""
    return hash_password("dummy-password-for-timing-equalisation")


def normalize_email(email: str) -> str:
    e = (email or "").strip().lower()
    if len(e) > 200 or not _EMAIL_RE.match(e):
        raise ValueError("Некорректный email")
    return e


def check_password_strength(password: str, email: str | None = None) -> str | None:
    """Возвращает текст ошибки или None, если пароль подходит."""
    if len(password) < 8:
        return "Пароль должен быть не короче 8 символов"
    if len(password) > 128:
        return "Пароль не должен быть длиннее 128 символов"
    if not any(ch.isalpha() for ch in password) or not any(ch.isdigit() for ch in password):
        return "Пароль должен содержать и буквы, и цифры"
    if email and password.lower() == email.lower():
        return "Пароль не должен совпадать с email"
    return None


def create_access_token(user_id: int, role: str, now: datetime | None = None) -> tuple[str, int]:
    now = now or datetime.now(timezone.utc)
    exp = now + timedelta(minutes=settings.access_token_minutes)
    token = jwt.encode(
        {"sub": str(user_id), "role": role, "iat": now, "exp": exp}, settings.secret_key, algorithm="HS256"
    )
    return token, settings.access_token_minutes * 60


def decode_access_token(token: str) -> int | None:
    """id пользователя из токена или None, если токен неверный или просрочен."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"], options={"require": ["exp", "sub"]})
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        return None
