"""Tasks the case matcher created in the local database (read-only). Needs the Harvey replay and the synthetic
scenarios to have run (see tests/conftest.py)."""
import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Case, Run, Task
from app.models.task import TaskKind, TaskPriority, TaskStatus


@pytest.fixture(scope="module")
def db():
    with SessionLocal() as session:
        yield session


def run_tasks(db, name_suffix):
    run = db.scalar(select(Run).where(Run.name.endswith(name_suffix)))
    if run is None:
        pytest.skip(f"run *{name_suffix} not in the local database")
    return list(db.scalars(select(Task).join(Case, Task.case_id == Case.id).where(Case.run_id == run.id)))


def test_harvey_one_pending_reach_block_task_per_case_all_flagged_by_the_end(db):
    tasks = run_tasks(db, "backtest:2017-08-25..2017-09-02")
    assert len(tasks) == 152
    assert {t.kind for t in tasks} == {TaskKind.reach_block}
    assert {t.status for t in tasks} == {TaskStatus.pending}  # nothing is dispatched automatically
    assert all(t.case.task_id == t.id for t in tasks)
    assert all(t.created_at == t.case.opened_at for t in tasks)  # R1 at the tick the Case opened
    assert all(t.verify_before_dispatch for t in tasks)  # every block had reconnected (R3)
    assert {t.priority for t in tasks} == {TaskPriority.low}
    assert all(t.verify_reason.startswith("latest evidence contradicts the Case (isolation: reconnected") for t in tasks)
    assert all(t.events[0].note.startswith("created by R1") and t.events[0].priority == TaskPriority.medium
               for t in tasks)


def test_scenario_tasks_reflect_urgency_and_escalation(db):
    tasks = run_tasks(db, "synthetic:listening")
    reasons = sorted(t.priority_reason for t in tasks if t.priority == TaskPriority.high)
    assert reasons.count("household asked for help") == 3
    assert "nominated neighbor reports trouble at the home" in reasons
    zone = [t for t in tasks if t.kind == TaskKind.reach_block]
    assert len(zone) == 1 and zone[0].case.escalated_at is not None
    assert all(t.status == TaskStatus.pending for t in tasks)
