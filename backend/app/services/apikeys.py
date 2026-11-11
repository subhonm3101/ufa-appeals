"""Ключи внешнего API: выпуск и проверка. В базе хранится только хеш ключа."""
import hashlib
import secrets

PREFIX = "ufa_"


def generate() -> str:
    """Новый ключ; показывается один раз, восстановить его по базе нельзя."""
    return PREFIX + secrets.token_urlsafe(32)


def digest(key: str) -> str:
    # ключ случайный и длинный, поэтому достаточно быстрого хеша без соли
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def shown_prefix(key: str) -> str:
    """Начало ключа для списка в админке (по нему ключ узнают, но не подбирают)."""
    return key[: len(PREFIX) + 4]
