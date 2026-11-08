"""Регистрация обращения в базе. Нужна тестовая база."""
import os

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

pytestmark = pytest.mark.skipif(
    not os.environ.get("APPEALS_TEST_DATABASE_URL"),
    reason="нужна тестовая база APPEALS_TEST_DATABASE_URL",
)

BODY = "Во дворе дома не работает освещение уже две недели."


@pytest.fixture
def session():
    from app.db import engine
    with Session(engine) as s:
        yield s


@pytest.fixture
def created(session):
    ids = []
    yield ids
    for i in ids:
        session.execute(text("DELETE FROM appeals WHERE id = :i"), {"i": i})
    session.commit()


def test_register_creates_new_appeal_with_number_and_history(session, created):
    from app.services.intake import NewAppeal, register
    r = register(session, NewAppeal(text=BODY, contact_email="a@b.ru", address_text="ул. Ленина, 1"))
    created.append(r.id)
    assert r.public_number.startswith("UFA-")
    row = session.execute(
        text("SELECT status, source, contact_email, due_at FROM appeals WHERE id = :i"), {"i": r.id}
    ).one()
    assert (row.status, row.source, row.contact_email, row.due_at) == ("new", "web", "a@b.ru", None)
    hist = session.execute(
        text("SELECT to_status FROM appeal_status_history WHERE appeal_id = :i"), {"i": r.id}
    ).all()
    assert [h.to_status for h in hist] == ["new"]


def test_unknown_district_rejected(session):
    from app.services.intake import IntakeError, NewAppeal, register
    with pytest.raises(IntakeError):
        register(session, NewAppeal(text=BODY, district_id=999999))


def test_same_external_id_returns_same_appeal(session, created):
    from app.services.intake import NewAppeal, register
    first = register(session, NewAppeal(text=BODY, source="api", external_id="test-ext-101"))
    created.append(first.id)
    second = register(session, NewAppeal(text=BODY + " Повтор.", source="api", external_id="test-ext-101"))
    assert second.id == first.id and second.public_number == first.public_number
