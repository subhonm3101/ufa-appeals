"""Права ролей: проверяем отказы 401 и 403 без базы данных (пользователя подменяем)."""
import pytest
from fastapi.testclient import TestClient

from app.auth import CurrentUser, get_current_user
from app.main import app

client = TestClient(app)

PROTECTED = [
    ("GET", "/api/appeals"), ("GET", "/api/categories"), ("GET", "/api/districts"),
    ("GET", "/api/stats/categories"), ("POST", "/api/import"),
    ("GET", "/api/analytics/timeseries"), ("GET", "/api/analytics/summary"),
    ("GET", "/api/analytics/heatmap"), ("GET", "/api/analytics/points"),
    ("GET", "/api/users"), ("POST", "/api/users"), ("PATCH", "/api/users/1"), ("GET", "/api/audit"),
    ("GET", "/api/auth/me"), ("POST", "/api/auth/change-password"),
]
# (роль, метод, адрес): запрещено
FORBIDDEN = [
    ("operator", "GET", "/api/analytics/summary"), ("operator", "GET", "/api/analytics/heatmap"),
    ("operator", "GET", "/api/analytics/timeseries"), ("operator", "GET", "/api/analytics/points"),
    ("analyst", "POST", "/api/import"), ("manager", "POST", "/api/import"),
    ("operator", "GET", "/api/users"), ("analyst", "GET", "/api/users"), ("manager", "GET", "/api/users"),
    ("manager", "POST", "/api/users"), ("operator", "PATCH", "/api/users/1"),
    ("operator", "GET", "/api/audit"), ("analyst", "GET", "/api/audit"), ("manager", "GET", "/api/audit"),
]


@pytest.fixture(autouse=True)
def _clean_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.mark.parametrize("method, url", PROTECTED)
def test_no_token_is_401(method, url):
    assert client.request(method, url).status_code == 401


@pytest.mark.parametrize("method, url", PROTECTED[:3])
def test_garbage_token_is_401(method, url):
    r = client.request(method, url, headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("role, method, url", FORBIDDEN)
def test_forbidden_roles_get_403(role, method, url):
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=1, email="t@t.ru", role=role)
    r = client.request(method, url, files={"file": ("pytest_x.csv", b"a,b\n1,2\n")} if method == "POST" and "import" in url else None)
    assert r.status_code == 403, (role, method, url, r.status_code)


def test_public_endpoints_need_no_token():
    assert client.get("/health").status_code == 200
