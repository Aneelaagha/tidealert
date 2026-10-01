"""Task actions through the API. Each test runs inside a transaction that is rolled back, so the local database
is left exactly as it was. Needs the Harvey replay and the listening scenario (see tests/conftest.py)."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import engine, get_db
from app.main import app
from app.models import Case, Responder, Run, Task
from app.models.task import TaskStatus
from app.services.confidence import case_confidence
from app.services.task_rules import apply_task_rules

LISTENING = "replay:2026-09-10T14:00..17:00Z:synthetic:listening"
HARVEY = "backtest:2017-08-25..2017-09-02"
END = "2026-09-10T17:00:00Z"


@pytest.fixture()
def tx():
    connection = engine.connect()
    outer = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    app.dependency_overrides[get_db] = lambda: session
    try:
        yield TestClient(app), session
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.close()
        outer.rollback()
        connection.close()


def run_named(db, name):
    run = db.scalar(select(Run).where(Run.name == name))
    if run is None:
        pytest.skip(f"run {name} not in the local database")
    return run


def tasks_of(db, run):
    return list(db.scalars(select(Task).join(Case, Task.case_id == Case.id).where(Case.run_id == run.id)))


def responders(db, run, n=2):
    rs = [Responder(run_id=run.id, name=f"Test responder {i}", role="synthetic responder (test)") for i in range(n)]
    db.add_all(rs)
    db.commit()  # releases the test savepoint only; the outer transaction is still rolled back at the end
    return rs


def help_task(db, run):
    return next(t for t in tasks_of(db, run) if t.priority_reason == "household asked for help")


def test_replay_runs_refuse_every_action(tx):
    client, db = tx
    run = run_named(db, HARVEY)
    task = tasks_of(db, run)[0]
    fake = Responder(run_id=run.id, name="should never be used", role="test")
    db.add(fake)
    db.commit()
    for path, body in [(f"/tasks/{task.id}/assign", {"actor": "tester", "responder_id": str(fake.id)}),
                       (f"/tasks/{task.id}/status", {"actor": "tester", "status": "cancelled"}),
                       (f"/tasks/{task.id}/clear-verify", {"actor": "tester"}),
                       (f"/cases/{task.case_id}/tasks", {"actor": "tester"})]:
        r = client.post(path, json=body)
        assert r.status_code == 422 and "replay" in r.json()["detail"], (path, r.text)


def test_assign_then_complete_and_read_back_in_time(tx):
    client, db = tx
    run = run_named(db, LISTENING)
    r1, r2 = responders(db, run)
    task = help_task(db, run)
    case = task.case
    at = "2026-09-10T16:00:00Z"
    r = client.post(f"/tasks/{task.id}/assign", json={"actor": "dispatcher A", "responder_id": str(r1.id), "at": at})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "assigned"
    db.refresh(case)
    assert case.status.value == "in_progress"  # assigning sets the Case in progress
    other = next(t for t in tasks_of(db, run) if t.id != task.id and t.status == TaskStatus.pending
                 and not t.verify_before_dispatch)
    busy = client.post(f"/tasks/{other.id}/assign", json={"actor": "dispatcher A", "responder_id": str(r1.id), "at": at})
    assert busy.status_code == 409 and "is assigned" in busy.json()["detail"]
    assert client.post(f"/tasks/{task.id}/status", json={"actor": "dispatcher A", "status": "en_route",
                                                         "at": "2026-09-10T16:15:00Z"}).status_code == 200
    done = client.post(f"/tasks/{task.id}/status", json={"actor": "dispatcher A", "status": "complete", "at": END,
                                                         "outcome": "household safe, sheltering upstairs"})
    assert done.status_code == 200 and done.json()["status"] == "complete"
    db.refresh(case)
    db.refresh(r1)
    assert case.task_id is None and case.status.value == "in_progress"  # completing never resolves the Case
    assert r1.status.value == "available"
    # Read back in time: pending before assignment, assigned at it, complete at the end.
    assert client.get(f"/tasks/{task.id}", params={"at": "2026-09-10T15:00:00Z"}).json()["status"] == "pending"
    assert client.get(f"/tasks/{task.id}", params={"at": at}).json()["status"] == "assigned"
    assert client.get(f"/tasks/{task.id}", params={"at": END}).json()["status"] == "complete"
    # Actions cannot go back in time.
    late = client.post(f"/cases/{case.id}/tasks", json={"actor": "dispatcher A", "at": END})
    assert late.status_code == 201
    back = client.post(f"/tasks/{late.json()['id']}/status", json={"actor": "x", "status": "cancelled",
                                                                   "at": "2026-09-10T15:00:00Z"})
    assert back.status_code == 422


def test_seen_ok_task_is_flagged_and_must_be_cleared_before_assignment(tx):
    client, db = tx
    run = run_named(db, LISTENING)
    (r1,) = responders(db, run, 1)
    flagged = next(t for t in tasks_of(db, run) if (t.verify_reason or "").startswith("an independent source"))
    blocked = client.post(f"/tasks/{flagged.id}/assign", json={"actor": "d", "responder_id": str(r1.id)})
    assert blocked.status_code == 409 and "verify before dispatch" in blocked.json()["detail"]
    cleared = client.post(f"/tasks/{flagged.id}/clear-verify", json={"actor": "d", "note": "called the neighbor back"})
    assert cleared.status_code == 200
    body = cleared.json()
    assert body["verify_before_dispatch"] is False and body["priority"] == "medium"  # restored from history
    assert client.post(f"/tasks/{flagged.id}/assign", json={"actor": "d", "responder_id": str(r1.id)}).status_code == 200


def test_responder_must_belong_to_the_run(tx):
    client, db = tx
    run = run_named(db, LISTENING)
    stranger = Responder(run_id=None, name="real responder (test)", role="test")
    db.add(stranger)
    db.commit()
    r = client.post(f"/tasks/{help_task(db, run).id}/assign", json={"actor": "d", "responder_id": str(stranger.id)})
    assert r.status_code == 422


def test_r1_after_close_only_on_new_evidence(tx):
    client, db = tx
    run = run_named(db, LISTENING)
    (r1,) = responders(db, run, 1)
    task = help_task(db, run)
    case = task.case
    client.post(f"/tasks/{task.id}/assign", json={"actor": "d", "responder_id": str(r1.id), "at": "2026-09-10T16:00:00Z"})
    client.post(f"/tasks/{task.id}/status", json={"actor": "d", "status": "unable_to_reach", "at": "2026-09-10T16:30:00Z"})
    db.refresh(case)
    later = datetime.fromisoformat("2026-09-10T16:45:00+00:00")
    conf = case_confidence(case, later)
    assert conf.word.value in ("single_source", "corroborated")  # still fresh support...
    assert apply_task_rules(case, conf, later) is None  # ...but nothing new since the close: no new task
    newer = next(c for c in case.contributions if c.direction.value == "supports")
    newer.first_observed_at = newer.observed_at = later  # simulate evidence first seen after the close
    assert apply_task_rules(case, case_confidence(case, later + timedelta(minutes=1)),
                            later + timedelta(minutes=1)) == "created"
    assert "after its last task closed" in case.task.created_by_rule


def test_map_zones_carry_task_summaries(client, runs):
    end = client.get("/map/zones", params={"run_id": runs["harvey"]["id"]}).json()["features"]
    with_task = [f["properties"] for f in end if f["properties"]["task_count"]]
    assert len(with_task) == 152
    assert {p["task_status"] for p in with_task} == {"pending"}
    assert all(p["task_verify"] and p["task_priority"] == "low" and len(p["task_anchor"]) == 2 for p in with_task)
    assert all(p["task_awaiting"] == 0 and p["task_flagged"] == 1 for p in with_task)  # counted per task
    start = client.get("/map/zones", params={"run_id": runs["harvey"]["id"], "at": runs["harvey"]["window_start"]})
    assert sum(f["properties"]["task_count"] for f in start.json()["features"]) == 0
    assert {"task_status", "task_kind", "task_priority"} <= set(runs["vocabulary"])
    cases = client.get("/cases", params={"run_id": runs["harvey"]["id"]}).json()["cases"]
    assert all(len(c["tasks"]) == 1 and c["tasks"][0]["events"] for c in cases)


def test_assignment_shows_in_the_zone_summary_from_its_time_on(tx):
    client, db = tx
    run = run_named(db, LISTENING)
    (r1,) = responders(db, run, 1)
    task = next(t for t in tasks_of(db, run) if t.priority_reason == "household asked for help"
                and t.case.zone.name.endswith("block B"))
    zone_id = str(task.case.zone_id)
    assert client.post(f"/tasks/{task.id}/assign", json={"actor": "d", "responder_id": str(r1.id),
                                                         "at": "2026-09-10T16:30:00Z"}).status_code == 200

    def block_b(at):
        feats = client.get("/map/zones", params={"run_id": str(run.id), "at": at}).json()["features"]
        return next(f["properties"] for f in feats if f["properties"]["zone_id"] == zone_id)

    before, after = block_b("2026-09-10T16:15:00Z"), block_b(END)
    assert (before["task_status"], before["task_awaiting"]) == ("pending", 1)
    assert (after["task_status"], after["task_awaiting"], after["task_count"]) == ("assigned", 0, 1)
