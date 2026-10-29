from datetime import datetime, timedelta, timezone

from app.services.priority_features import (COMPONENTS, DEFAULT_CONFIG, compute_components,
                                            is_social, score_from_components, urgency_level)

AS_OF = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


def ago(days):
    return AS_OF - timedelta(days=days)


def test_urgency_levels():
    assert urgency_level("Оголённые провода лежат на земле") == 3
    assert urgency_level("Заносит машины на повороте") == 2
    assert urgency_level("На дороге яма") == 1
    assert urgency_level("Просьба рассмотреть вопрос") == 0


def test_social_object():
    assert is_social("Возле школы нет освещения")
    assert not is_social("Во дворе лежит мусор")


def test_weights_sum_to_one():
    assert abs(sum(DEFAULT_CONFIG.weights.values()) - 1.0) < 1e-9


def test_big_fresh_dangerous_cluster_beats_single_old_minor():
    big = compute_components([("Оголённые провода у школы", ago(d)) for d in (0, 1, 2, 3, 6)], "lighting", AS_OF)
    small = compute_components([("На дороге яма", ago(20))], "roads", AS_OF)
    assert score_from_components(big["components"]) > score_from_components(small["components"])


def test_components_in_range():
    r = compute_components([("Яма", ago(1)), ("Яма", ago(9))], "roads", AS_OF)
    assert set(r["components"]) == set(COMPONENTS)
    assert all(0.0 <= v <= 1.0 for v in r["components"].values())
    assert 0.0 <= score_from_components(r["components"]) <= 100.0


def test_appeals_after_as_of_are_ignored():
    items = [("Яма", ago(2)), ("Яма", AS_OF + timedelta(days=1))]
    assert compute_components(items, "roads", AS_OF)["raw"]["appeals"] == 1
    assert compute_components([("Яма", AS_OF + timedelta(days=1))], "roads", AS_OF) is None


def test_dynamics_rises_with_recent_appeals():
    old = compute_components([("Яма", ago(d)) for d in (10, 11, 12)], "roads", AS_OF)
    fresh = compute_components([("Яма", ago(d)) for d in (0, 1, 2)], "roads", AS_OF)
    assert fresh["components"]["dynamics"] > old["components"]["dynamics"]