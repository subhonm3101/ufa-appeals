"""Шаг 14.5: новое обращение получает кластер и приоритет, пустой кластер удаляется вместе с обращением."""
import os

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

pytestmark = pytest.mark.skipif(
    not os.environ.get("APPEALS_TEST_DATABASE_URL"),
    reason="нужна тестовая база (APPEALS_TEST_DATABASE_URL)",
)

BODY = "Во дворе дома на улице Ленина уже неделю не горит фонарь, вечером ходить опасно"


@pytest.fixture
def session():
    from app.db import engine

    with Session(engine) as s:
        yield s


@pytest.fixture
def made(session):
    ids = []
    yield ids
    for i in ids:
        session.execute(text("DELETE FROM appeals WHERE id = :i"), {"i": i})
    session.commit()


def _register(session, made, **kw):
    from app.services.intake import NewAppeal, register

    r = register(session, NewAppeal(text=BODY, **kw))
    made.append(r.id)
    return r


def _cluster_of(session, appeal_id):
    return session.execute(
        text("SELECT cluster_id FROM appeals WHERE id = :i"), {"i": appeal_id}
    ).scalar_one()


def test_new_appeal_gets_cluster_and_priority(session, made):
    r = _register(session, made)
    cid = _cluster_of(session, r.id)
    assert cid is not None
    cl = session.execute(
        text("SELECT appeals_count, status FROM clusters WHERE id = :c"), {"c": cid}
    ).one()
    assert cl.appeals_count == 1 and cl.status == "open"
    rows = session.execute(
        text("SELECT score, method, as_of, factors FROM priority_scores WHERE cluster_id = :c"),
        {"c": cid},
    ).fetchall()
    assert len(rows) == 1
    assert rows[0].method == "rules_v1" and rows[0].as_of is not None
    assert 0 <= rows[0].score <= 100
    assert "components" in rows[0].factors


def test_coordinates_go_to_cluster_centroid(session, made):
    r = _register(session, made, lat=54.7388, lon=55.9721)
    cid = _cluster_of(session, r.id)
    lat, lon = session.execute(
        text("SELECT centroid_lat, centroid_lon FROM clusters WHERE id = :c"), {"c": cid}
    ).one()
    assert abs(lat - 54.7388) < 1e-6 and abs(lon - 55.9721) < 1e-6


def test_refresh_keeps_single_priority_row(session, made):
    from app.services import pipeline

    r = _register(session, made)
    cid = _cluster_of(session, r.id)
    pipeline.refresh_priority(session, cid)
    session.commit()
    n = session.execute(
        text("SELECT count(*) FROM priority_scores WHERE cluster_id = :c AND method = 'rules_v1'"),
        {"c": cid},
    ).scalar_one()
    assert n == 1


def test_empty_cluster_removed_with_last_appeal(session, made):
    r = _register(session, made)
    cid = _cluster_of(session, r.id)
    session.execute(text("DELETE FROM appeals WHERE id = :i"), {"i": r.id})
    session.commit()
    made.remove(r.id)
    assert session.execute(text("SELECT count(*) FROM clusters WHERE id = :c"), {"c": cid}).scalar_one() == 0
    assert session.execute(
        text("SELECT count(*) FROM priority_scores WHERE cluster_id = :c"), {"c": cid}
    ).scalar_one() == 0


def test_cluster_with_other_members_survives(session, made):
    r = _register(session, made)
    other = _register(session, made)
    cid = _cluster_of(session, r.id)
    session.execute(text("UPDATE appeals SET cluster_id = :c WHERE id = :i"), {"c": cid, "i": other.id})
    session.commit()
    session.execute(text("DELETE FROM appeals WHERE id = :i"), {"i": r.id})
    session.commit()
    made.remove(r.id)
    assert session.execute(text("SELECT count(*) FROM clusters WHERE id = :c"), {"c": cid}).scalar_one() == 1


def test_category_change_updates_cluster(session, made):
    from app.services import pipeline

    cat = session.execute(text("SELECT id FROM categories ORDER BY id LIMIT 1")).scalar()
    if cat is None:
        pytest.skip("в тестовой базе нет категорий")
    r = _register(session, made)
    cid = _cluster_of(session, r.id)
    session.execute(text("UPDATE appeals SET category_id = :c WHERE id = :i"), {"c": cat, "i": r.id})
    pipeline.on_category_changed(session, r.id)
    session.commit()
    got = session.execute(text("SELECT category_id FROM clusters WHERE id = :c"), {"c": cid}).scalar_one()
    assert got == cat
    n = session.execute(
        text("SELECT count(*) FROM priority_scores WHERE cluster_id = :c AND method = 'rules_v1'"), {"c": cid}
    ).scalar_one()
    assert n == 1


def test_closing_removes_cluster_from_queue(session, made, make_user):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import pipeline

    client = TestClient(app)
    user = make_user("admin")

    def total():
        r = client.get("/api/priority/queue", params={"limit": 1}, headers=user.headers)
        assert r.status_code == 200, r.text
        return r.json()["total"]

    r = _register(session, made)
    cid = _cluster_of(session, r.id)
    before = total()
    session.execute(text("UPDATE appeals SET status = 'resolved' WHERE id = :i"), {"i": r.id})
    assert pipeline.on_status_changed(session, r.id) == "closed"
    session.commit()
    assert total() == before - 1
    session.execute(text("UPDATE appeals SET status = 'in_progress' WHERE id = :i"), {"i": r.id})
    assert pipeline.on_status_changed(session, r.id) == "open"
    session.commit()
    assert total() == before
    n = session.execute(
        text("SELECT count(*) FROM priority_scores WHERE cluster_id = :c AND method = 'rules_v1'"), {"c": cid}
    ).scalar_one()
    assert n == 1


def test_cluster_stays_open_while_any_member_open(session, made):
    from app.services import pipeline

    a = _register(session, made)
    b = _register(session, made)
    cid = _cluster_of(session, a.id)
    session.execute(text("UPDATE appeals SET cluster_id = :c WHERE id = :i"), {"c": cid, "i": b.id})
    session.execute(text("UPDATE appeals SET status = 'rejected' WHERE id = :i"), {"i": a.id})
    assert pipeline.on_status_changed(session, a.id) == "open"
    session.commit()


def test_public_form_coordinates(session, made):
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    r = client.post("/api/public/appeals", data={"text": BODY, "lat": "54.7388", "lon": "55.9721"})
    assert r.status_code == 201, r.text
    row = session.execute(
        text("SELECT id, lat, lon, cluster_id FROM appeals WHERE public_number = :n"),
        {"n": r.json()["public_number"]},
    ).one()
    made.append(row.id)
    assert abs(row.lat - 54.7388) < 1e-6 and row.cluster_id is not None
    clat = session.execute(
        text("SELECT centroid_lat FROM clusters WHERE id = :c"), {"c": row.cluster_id}
    ).scalar_one()
    assert abs(clat - 54.7388) < 1e-6
    far = client.post("/api/public/appeals", data={"text": BODY, "lat": "10", "lon": "10"})
    assert far.status_code == 422
