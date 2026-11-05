"""Правила обработки обращения (без базы данных)."""
from datetime import datetime, timezone

import pytest

from app.services import workflow as w


def ok(current, target, role="operator", assignee=False, comment="причина", response="ответ"):
    return w.check_transition(current, target, role, assignee, comment, response)


@pytest.mark.parametrize(
    "current,target",
    [
        ("new", "accepted"), ("new", "rejected"),
        ("accepted", "in_progress"), ("accepted", "rejected"),
        ("in_progress", "waiting"), ("in_progress", "resolved"), ("in_progress", "rejected"),
        ("waiting", "in_progress"), ("waiting", "resolved"), ("waiting", "rejected"),
    ],
)
def test_allowed_transitions_for_operator(current, target):
    assert ok(current, target) is None


@pytest.mark.parametrize(
    "current,target",
    [("new", "resolved"), ("new", "in_progress"), ("accepted", "resolved"), ("waiting", "accepted")],
)
def test_forbidden_transitions(current, target):
    problem = ok(current, target, role="manager")
    assert problem is not None and problem[0] == 409


def test_same_status_is_conflict():
    assert ok("new", "new")[0] == 409


@pytest.mark.parametrize("current,target", [("resolved", "in_progress"), ("rejected", "accepted")])
def test_reopen_only_for_manager_and_admin(current, target):
    assert ok(current, target, role="operator")[0] == 403
    assert ok(current, target, role="executor", assignee=True)[0] == 403
    assert ok(current, target, role="manager") is None
    assert ok(current, target, role="admin") is None


def test_rejection_needs_reason():
    assert ok("new", "rejected", comment=None)[0] == 422
    assert ok("new", "rejected", comment="   ")[0] == 422


def test_resolution_needs_response_text():
    assert ok("in_progress", "resolved", response=None)[0] == 422
    assert ok("in_progress", "resolved", response="  ")[0] == 422


def test_executor_only_own_and_only_working_statuses():
    assert ok("accepted", "in_progress", role="executor", assignee=False)[0] == 403
    assert ok("accepted", "in_progress", role="executor", assignee=True) is None
    assert ok("in_progress", "rejected", role="executor", assignee=True)[0] == 403
    assert ok("new", "accepted", role="executor", assignee=True)[0] == 403


def test_allowed_transitions_for_buttons():
    assert w.allowed_transitions("new", "operator", False) == ["accepted", "rejected"]
    assert w.allowed_transitions("new", "analyst", False) == []
    assert w.allowed_transitions("resolved", "operator", False) == []
    assert w.allowed_transitions("resolved", "manager", False) == ["in_progress"]
    assert w.allowed_transitions("in_progress", "executor", True) == ["waiting", "resolved"]
    assert w.allowed_transitions("in_progress", "executor", False) == []


def test_every_status_has_label_and_transitions():
    assert set(w.STATUS_LABELS) == set(w.STATUSES) == set(w.TRANSITIONS)
    for targets in w.TRANSITIONS.values():
        assert set(targets) <= set(w.STATUSES)


def test_due_date_is_thirty_days():
    created = datetime(2026, 3, 5, 10, 0, tzinfo=timezone.utc)
    assert w.due_date(created) == datetime(2026, 4, 4, 10, 0, tzinfo=timezone.utc)
