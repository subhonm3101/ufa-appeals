"""Версия в токене доступа (шаг 12.1), без базы."""
from app.services.security import create_access_token, decode_access_claims, decode_access_token


def test_token_carries_version():
    token, _ = create_access_token(7, "operator", version=3)
    assert decode_access_claims(token) == (7, 3)
    assert decode_access_token(token) == 7


def test_default_version_is_zero():
    token, _ = create_access_token(7, "operator")
    assert decode_access_claims(token) == (7, 0)


def test_token_without_version_counts_as_zero():
    import jwt
    from datetime import datetime, timedelta, timezone
    from app.config import settings
    old = jwt.encode(
        {"sub": "5", "role": "admin", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        settings.secret_key, algorithm="HS256",
    )
    assert decode_access_claims(old) == (5, 0)


def test_garbage_and_foreign_signature_rejected():
    import jwt
    from datetime import datetime, timedelta, timezone
    assert decode_access_claims("не токен") is None
    forged = jwt.encode(
        {"sub": "1", "tv": 0, "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}, "другой-ключ-подписи-123456789012", algorithm="HS256",
    )
    assert decode_access_claims(forged) is None
