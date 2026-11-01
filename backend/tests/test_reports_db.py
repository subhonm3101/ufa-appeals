"""Тесты выгрузки отчёта в Excel. Нужна тестовая база (APPEALS_TEST_DATABASE_URL)."""
import os
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

pytestmark = pytest.mark.skipif(
    not os.environ.get("APPEALS_TEST_DATABASE_URL"),
    reason="нужна тестовая база APPEALS_TEST_DATABASE_URL",
)

URL = "/api/reports/summary.xlsx"
PERIOD = {"date_from": "2026-01-01", "date_to": "2026-01-31"}
SHEETS = ["Сводка", "Динамика", "Прогноз", "Аномалии", "Приоритеты"]
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def test_requires_login(client):
    assert client.get(URL).status_code == 401


def test_operator_forbidden(client, make_user):
    user = make_user("operator")
    assert client.get(URL, params=PERIOD, headers=user.headers).status_code == 403


@pytest.mark.parametrize("role", ["analyst", "manager", "admin"])
def test_workbook_has_all_sheets(client, make_user, role):
    user = make_user(role)
    r = client.get(URL, params=PERIOD, headers=user.headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(XLSX)
    assert "attachment" in r.headers["content-disposition"]
    wb = load_workbook(BytesIO(r.content))
    assert wb.sheetnames == SHEETS
    assert wb["Сводка"]["A1"].value.startswith("Отчёт по обращениям")


def test_period_start_after_end_rejected(client, make_user):
    user = make_user("analyst")
    r = client.get(URL, params={"date_from": "2026-02-01", "date_to": "2026-01-01"},
                   headers=user.headers)
    assert r.status_code == 422


def test_too_long_period_rejected(client, make_user):
    user = make_user("analyst")
    r = client.get(URL, params={"date_from": "2000-01-01", "date_to": "2026-01-01"},
                   headers=user.headers)
    assert r.status_code == 422


def test_unknown_category_and_district(client, make_user):
    user = make_user("analyst")
    assert client.get(URL, params={**PERIOD, "category": "no_such"},
                      headers=user.headers).status_code == 404
    assert client.get(URL, params={**PERIOD, "district": "no_such"},
                      headers=user.headers).status_code == 404


def test_export_is_written_to_audit_log(client, make_user):
    from sqlalchemy import text

    from app.db import engine
    user = make_user("manager")
    assert client.get(URL, params=PERIOD, headers=user.headers).status_code == 200
    with engine.connect() as c:
        n = c.execute(text(
            "SELECT count(*) FROM audit_log WHERE user_id = :u AND action = 'report_export'"
        ), {"u": user.id}).scalar_one()
    assert n == 1
