"""Публичный API приёма обращений и вложения. Нужна тестовая база."""
import os

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    not os.environ.get("APPEALS_TEST_DATABASE_URL"),
    reason="нужна тестовая база APPEALS_TEST_DATABASE_URL",
)

BODY = "Во дворе дома не работает освещение уже две недели."
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 50


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.api import public
    from app.main import app
    from app.services import attachments

    monkeypatch.setattr(attachments, "UPLOAD_DIR", tmp_path)
    public.submit_limiter.reset()
    public.lookup_limiter.reset()
    yield TestClient(app)
    public.submit_limiter.reset()
    public.lookup_limiter.reset()


@pytest.fixture
def cleanup():
    """Тесты с make_user перечисляют её раньше cleanup: обращения удаляются до пользователей."""
    numbers = []
    yield numbers
    from app.db import engine
    with engine.begin() as c:
        for n in numbers:
            c.execute(text("DELETE FROM appeals WHERE public_number = :n"), {"n": n})


def post(client, cleanup=None, files=None, **fields):
    data = {"text": BODY, **fields}
    r = client.post("/api/public/appeals", data=data, files=files)
    if cleanup is not None and r.status_code == 201:
        cleanup.append(r.json()["public_number"])
    return r


def count_appeals(marker):
    from app.db import engine
    with engine.connect() as c:
        return c.execute(text("SELECT count(*) FROM appeals WHERE text = :t"), {"t": marker}).scalar_one()


def test_submit_without_login_returns_number(client, cleanup):
    r = post(client, cleanup, contact_email="a@b.ru")
    assert r.status_code == 201
    assert r.json()["public_number"].startswith("UFA-")


def test_bad_text_gives_422_with_message(client):
    r = post(client, text="мало")
    assert r.status_code == 422
    assert "минимум" in r.json()["detail"]


def test_status_lookup_hides_private_data(client, cleanup):
    number = post(client, cleanup, contact_email="secret@b.ru", address_text="ул. Ленина, 1").json()["public_number"]
    r = client.get(f"/api/public/appeals/{number.lower()}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "new" and body["status_label"] == "Зарегистрировано"
    assert body["response_text"] is None
    assert "secret@b.ru" not in r.text and "Ленина" not in r.text and BODY not in r.text


@pytest.mark.parametrize("number", ["UFA-2026-999999", "abc", "UFA-26-1"])
def test_unknown_number_is_404(client, number):
    assert client.get(f"/api/public/appeals/{number}").status_code == 404


def test_submit_is_rate_limited(client, cleanup):
    for _ in range(5):
        assert post(client, cleanup).status_code == 201
    assert post(client).status_code == 429


def test_districts_list(client):
    r = client.get("/api/public/districts")
    assert r.status_code == 200 and isinstance(r.json(), list)


def test_photos_are_saved_and_visible_to_staff(client, make_user, cleanup):
    r = post(client, cleanup, files=[("files", ("фото 1.png", PNG, "image/png"))])
    assert r.status_code == 201
    from app.db import engine
    with engine.connect() as c:
        appeal_id = c.execute(
            text("SELECT id FROM appeals WHERE public_number = :n"), {"n": r.json()["public_number"]}
        ).scalar_one()
    staff = make_user("operator")
    listing = client.get(f"/api/appeals/{appeal_id}/attachments", headers=staff.headers)
    assert listing.status_code == 200 and len(listing.json()) == 1
    item = listing.json()[0]
    assert item["content_type"] == "image/png" and item["size_bytes"] == len(PNG)
    got = client.get(f"/api/attachments/{item['id']}/file", headers=staff.headers)
    assert got.status_code == 200 and got.content == PNG
    assert got.headers["content-type"] == "image/png"


def test_attachments_require_login(client, cleanup):
    post(client, cleanup, files=[("files", ("a.png", PNG, "image/png"))])
    assert client.get("/api/attachments/1/file").status_code == 401
    assert client.get("/api/appeals/1/attachments").status_code == 401


def test_executor_sees_only_own_appeal_attachments(client, make_user, cleanup):
    r = post(client, cleanup, files=[("files", ("a.png", PNG, "image/png"))])
    from app.db import engine
    with engine.connect() as c:
        appeal_id = c.execute(
            text("SELECT id FROM appeals WHERE public_number = :n"), {"n": r.json()["public_number"]}
        ).scalar_one()
    executor = make_user("executor")
    assert client.get(f"/api/appeals/{appeal_id}/attachments", headers=executor.headers).status_code == 404
    with engine.begin() as c:
        c.execute(text("UPDATE appeals SET assignee_id = :u WHERE id = :i"), {"u": executor.id, "i": appeal_id})
    assert client.get(f"/api/appeals/{appeal_id}/attachments", headers=executor.headers).status_code == 200


def test_fake_image_rejected_and_no_appeal_created(client):
    marker = "Уникальный текст для проверки отклонения файла 7f3a"
    r = post(client, text=marker, files=[("files", ("virus.jpg", b"MZ\x90 not an image", "image/jpeg"))])
    assert r.status_code == 422 and "JPEG" in r.json()["detail"]
    assert count_appeals(marker) == 0


def test_too_many_photos_rejected(client):
    files = [("files", (f"{i}.png", PNG, "image/png")) for i in range(4)]
    r = post(client, files=files)
    assert r.status_code == 422 and "не больше 3" in r.json()["detail"]
