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
