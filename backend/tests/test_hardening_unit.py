"""Настройки для публикации, заголовки безопасности, адрес клиента за прокси (шаг 12.4). База не нужна."""
import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.auth import client_ip
from app.config import DEFAULT_SECRET_KEY, Settings, production_problems, settings


def make_request(peer, forwarded=None):
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "client": (peer, 5000) if peer else None, "headers": headers})


@pytest.fixture
def proxy(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxies", "10.0.0.1, 10.0.0.2")


def test_client_ip_without_proxy_config_ignores_header():
    assert client_ip(make_request("203.0.113.5", "1.2.3.4")) == "203.0.113.5"


def test_untrusted_peer_cannot_spoof(proxy):
    assert client_ip(make_request("203.0.113.5", "1.2.3.4")) == "203.0.113.5"


def test_trusted_proxy_gives_real_client(proxy):
    assert client_ip(make_request("10.0.0.1", "198.51.100.7")) == "198.51.100.7"


def test_spoofed_left_part_of_chain_is_ignored(proxy):
    assert client_ip(make_request("10.0.0.1", "6.6.6.6, 198.51.100.7, 10.0.0.2")) == "198.51.100.7"


def test_trusted_proxy_without_header_and_no_peer(proxy):
    assert client_ip(make_request("10.0.0.1")) == "10.0.0.1"
    assert client_ip(make_request(None)) is None


def test_development_has_no_problems():
    assert production_problems(Settings(environment="development", secret_key=DEFAULT_SECRET_KEY)) == []


def test_production_rejects_default_and_short_key():
    assert production_problems(Settings(environment="production", secret_key=DEFAULT_SECRET_KEY, cors_origins="https://a.ru"))
    assert production_problems(Settings(environment="production", secret_key="короткий", cors_origins="https://a.ru"))


def test_production_rejects_localhost_origin():
    bad = Settings(environment="production", secret_key="x" * 40)
    assert any("CORS" in p for p in production_problems(bad))


def test_production_accepts_proper_settings():
    ok = Settings(environment="production", secret_key="x" * 40, cors_origins="https://appeals.example.ru")
    assert production_problems(ok) == []


def test_security_headers_present():
    from app.main import app
    r = TestClient(app).get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "same-origin"
    assert "strict-transport-security" not in r.headers  # только в production


def test_api_responses_are_not_cached():
    from app.main import app
    r = TestClient(app).get("/api/auth/me")
    assert r.status_code == 401
    assert r.headers["cache-control"] == "no-store"
