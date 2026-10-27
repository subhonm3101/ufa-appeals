"""Пароли и токены: без базы данных."""
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.config import settings
from app.services.security import (
    check_password_strength, create_access_token, decode_access_token, hash_password,
    normalize_email, verify_password,
)


def test_hash_and_verify():
    h = hash_password("Secret-123")
    assert h.startswith("scrypt$") and "Secret-123" not in h
    assert verify_password("Secret-123", h)
    assert not verify_password("secret-123", h)
    assert not verify_password("", h)


def test_hashes_are_salted():
    assert hash_password("Secret-123") != hash_password("Secret-123")


@pytest.mark.parametrize("bad", ["", "plain", "scrypt$1$2", "scrypt$x$8$1$AAAA$AAAA", "bcrypt$a$b$c$d$e"])
def test_verify_rejects_garbage_hash(bad):
    assert verify_password("x", bad) is False


def test_token_roundtrip():
    token, ttl = create_access_token(42, "analyst")
    assert decode_access_token(token) == 42 and ttl == settings.access_token_minutes * 60


def test_expired_token_rejected():
    old = datetime.now(timezone.utc) - timedelta(minutes=settings.access_token_minutes + 5)
    token, _ = create_access_token(42, "admin", now=old)
    assert decode_access_token(token) is None


def test_tampered_and_foreign_tokens_rejected():
    token, _ = create_access_token(42, "operator")
    head, body, sig = token.split(".")
    assert decode_access_token(f"{head}.{body}.{sig[:-2]}xx") is None
    forged = jwt.encode({"sub": "1", "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, "другой-ключ", algorithm="HS256")
    assert decode_access_token(forged) is None
    assert decode_access_token("мусор") is None and decode_access_token("") is None


def test_unsigned_token_rejected():
    none_token = jwt.encode({"sub": "1", "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, None, algorithm="none")
    assert decode_access_token(none_token) is None


@pytest.mark.parametrize("pw, ok", [
    ("short1", False), ("onlyletters", False), ("12345678", False),
    ("Abcdefg1", True), ("x" * 129 + "1", False),
])
def test_password_strength(pw, ok):
    assert (check_password_strength(pw) is None) is ok


def test_password_equal_to_email_rejected():
    assert check_password_strength("User1234@mail.ru", "user1234@mail.ru") is not None


def test_normalize_email():
    assert normalize_email("  Ivan@Example.COM ") == "ivan@example.com"
    for bad in ["", "no-at", "a@b", "a b@c.ru", "x" * 201 + "@a.ru"]:
        with pytest.raises(ValueError):
            normalize_email(bad)
