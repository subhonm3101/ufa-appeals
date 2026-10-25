"""Проверка параметров аналитики: база данных не нужна (ошибки до запросов)."""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


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
