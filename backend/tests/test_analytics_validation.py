"""Проверка параметров аналитики: база данных не нужна (ошибки до запросов)."""
import pytest
from fastapi.testclient import TestClient

from app.auth import CurrentUser, get_current_user
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _as_admin():
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=1, email="t@t.ru", role="admin")
    yield
    app.dependency_overrides.clear()


@pytest.mark.parametrize("url, params", [
    ("/api/analytics/timeseries", {"date_from": "2026-02-01", "date_to": "2026-01-01"}),
    ("/api/analytics/timeseries", {"granularity": "year"}),
    ("/api/analytics/summary", {"date_from": "2000-01-01", "date_to": "2026-01-01"}),
    ("/api/analytics/points", {"date_from": "2026-02-01", "date_to": "2026-01-01"}),
    ("/api/analytics/points", {"limit": 9999}),
    ("/api/analytics/points", {"limit": 0}),
    ("/api/analytics/heatmap", {"date_from": "не дата"}),
])
def test_invalid_params_return_422(url, params):
    assert client.get(url, params=params).status_code == 422
