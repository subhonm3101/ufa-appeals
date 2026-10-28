import os
import uuid

import pytest

from ml.register_models import build_metrics, upsert_model

SINGLE = {"A_grouped": {"test": {"accuracy": 0.97, "macro_f1": 0.96}, "best_C": 30}}
MULTI = {"seeds": [1, 2], "versions": {"scikit-learn": "x"},
         "summary": {"A_grouped": {"tfidf": {"macro_f1": {"mean": 0.9, "std": 0.01}}}}}


def test_build_metrics():
    m = build_metrics(SINGLE, MULTI, "tfidf")
    assert m["single_run"]["A_grouped"]["macro_f1"] == 0.96
    assert m["multiseed"]["macro_f1_mean_std"]["A_grouped"]["mean"] == 0.9
    assert "multiseed" not in build_metrics(SINGLE, None, "tfidf")


DSN = os.environ.get("APPEALS_TEST_DATABASE_URL")


@pytest.mark.skipif(not DSN, reason="нет APPEALS_TEST_DATABASE_URL")
def test_upsert_is_idempotent():
    import psycopg2
    conn = psycopg2.connect(DSN.replace("postgresql+psycopg2://", "postgresql://"))
    version = "pytest-" + uuid.uuid4().hex[:8]
    try:
        with conn, conn.cursor() as cur:
            a, created1 = upsert_model(cur, "classifier", "pytest_model", version, {"v": 1})
            b, created2 = upsert_model(cur, "classifier", "pytest_model", version, {"v": 2})
            assert a == b and created1 and not created2
            cur.execute("SELECT metrics->>'v' FROM ml_models WHERE id = %s", (a,))
            assert cur.fetchone()[0] == "2"
    finally:
        with conn, conn.cursor() as cur:
            cur.execute("DELETE FROM ml_models WHERE name = 'pytest_model' AND version = %s", (version,))
        conn.close()
