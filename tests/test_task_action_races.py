"""Concurrent task actions against the real database: separate connections, real commits, real row locks.
A rolled-back single-session test can't show a race, so each test builds its own temporary run, Cases and
responders (a scenario run named test:row-lock-race:...), races threads with their own sessions, and deletes all
of it afterwards. Harvey, the scenarios and the mixed run are never touched."""
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Case, Responder, Run, Task, Zone
from app.models.case import CaseStatus, ConfidenceWord
from app.models.responder import ResponderStatus
from app.models.run import RunMode
from app.services import task_actions
from app.services.isolation_cases import clear_cases
from app.services.task_actions import TaskActionError

START = datetime(2030, 1, 1, tzinfo=timezone.utc)
ACT_AT = START + timedelta(hours=1)
ACTOR = "test:row-lock-race"


@contextmanager
def temporary_world(cases=1, responders=10, follow_up=True):
    """A throwaway scenario run with Cases (each with a pending follow-up task) and responders; always removed."""
    tag = f"test:row-lock-race:{uuid.uuid4()}"
    with SessionLocal() as db:
        zone_id = db.scalar(select(Zone.id).where(Zone.region.like("synthetic:%")).limit(1))
        run = Run(name=tag, mode=RunMode.scenario, description="temporary: concurrency test",
                  window_start=START, window_end=START + timedelta(days=1))
        db.add(run)
        db.flush()
        made = [Case(zone_id=zone_id, run_id=run.id, source=tag, status=CaseStatus.open, opened_at=START,
                     inference_sentence="temporary Case for a concurrency test",
                     confidence_word=ConfidenceWord.single_source) for _ in range(cases)]
        db.add_all(made)
        db.flush()
        if follow_up:
            for case in made:
                task_actions.open_follow_up(db, case, ACTOR, at=START)
        rs = [Responder(run_id=run.id, name=f"race responder {i}", role="test") for i in range(responders)]
        db.add_all(rs)
        db.commit()
        world = {"run": run.id, "cases": [c.id for c in made], "responders": [r.id for r in rs],
                 "tasks": [c.task.id for c in made] if follow_up else []}
    try:
        yield world
    finally:
        with SessionLocal() as db:
            clear_cases(db, tag)
            for r in db.scalars(select(Responder).where(Responder.run_id == world["run"])):
                db.delete(r)
            db.delete(db.get(Run, world["run"]))
            db.commit()


def race(n, act):
    """Run act(i, db) in n threads, released together, each in its own session; returns 'ok' or the HTTP code."""
    barrier, results = threading.Barrier(n), [None] * n

    def worker(i):
        with SessionLocal() as db:
            # Open the connection before the barrier: otherwise, with a cold pool, the first thread finishes its whole
            # transaction while the others are still connecting, and the race never happens.
            db.execute(select(1))
            db.commit()
            barrier.wait()
            try:
                act(i, db)
                db.commit()
                results[i] = "ok"
            except TaskActionError as exc:
                db.rollback()
                results[i] = exc.status_code
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def test_concurrent_assigns_of_one_task_succeed_exactly_once():
    with temporary_world(cases=1, responders=10) as w:
        task_id = w["tasks"][0]

        def assign(i, db):
            task_actions.assign(db, db.get(Task, task_id), db.get(Responder, w["responders"][i]), ACTOR, at=ACT_AT)
        results = race(10, assign)
        assert results.count("ok") == 1 and results.count(409) == 9, results
        with SessionLocal() as db:
            task = db.get(Task, task_id)
            assert sum(e.note.startswith("assigned to") for e in task.events) == 1  # one assignment in the history
            busy = [r for r in db.scalars(select(Responder).where(Responder.run_id == w["run"]))
                    if r.status == ResponderStatus.assigned]
            assert len(busy) == 1 and busy[0].id == task.assigned_responder_id


def test_one_responder_cannot_be_assigned_to_two_tasks_at_once():
    with temporary_world(cases=2, responders=1) as w:
        responder_id = w["responders"][0]

        def assign(i, db):
            task_actions.assign(db, db.get(Task, w["tasks"][i]), db.get(Responder, responder_id), ACTOR, at=ACT_AT)
        results = race(2, assign)
        assert sorted(map(str, results)) == ["409", "ok"], results
        with SessionLocal() as db:
            holders = db.scalars(select(Task).where(Task.assigned_responder_id == responder_id)).all()
            assert len(holders) == 1


def test_concurrent_completes_record_one_completion():
    with temporary_world(cases=1, responders=1) as w:
        task_id = w["tasks"][0]
        with SessionLocal() as db:
            task_actions.assign(db, db.get(Task, task_id), db.get(Responder, w["responders"][0]), ACTOR, at=ACT_AT)
            db.commit()

        def complete(i, db):
            task_actions.set_status(db, db.get(Task, task_id), task_actions.TaskStatus.complete, ACTOR, at=ACT_AT)
        results = race(5, complete)
        assert results.count("ok") == 1 and results.count(409) == 4, results
        with SessionLocal() as db:
            assert sum(e.status.value == "complete" for e in db.get(Task, task_id).events) == 1


def test_concurrent_follow_ups_open_one_task():
    with temporary_world(cases=1, responders=0, follow_up=False) as w:
        case_id = w["cases"][0]

        def follow_up(i, db):
            task_actions.open_follow_up(db, db.get(Case, case_id), ACTOR, at=ACT_AT)
        results = race(5, follow_up)
        assert results.count("ok") == 1 and results.count(409) == 4, results
        with SessionLocal() as db:
            assert len(db.scalars(select(Task).where(Task.case_id == case_id)).all()) == 1


def test_two_actions_in_one_transaction_keep_the_first():
    """The lock re-reads the row; it must not throw away an earlier action in the same transaction (clear-verify,
    then assign, without a commit in between)."""
    with temporary_world(cases=1, responders=1) as w:
        with SessionLocal() as db:
            task = db.get(Task, w["tasks"][0])
            task.verify_before_dispatch, task.verify_reason = True, "test: flagged"
            db.commit()
            task_actions.clear_verify(db, task, ACTOR, at=ACT_AT)  # not committed yet
            task_actions.assign(db, task, db.get(Responder, w["responders"][0]), ACTOR, at=ACT_AT)
            db.commit()
        with SessionLocal() as db:
            task = db.get(Task, w["tasks"][0])
            assert task.status.value == "assigned" and task.verify_before_dispatch is False


def test_the_temporary_world_leaves_nothing_behind():
    with temporary_world(cases=1, responders=2) as w:
        tag_run = w["run"]
    with SessionLocal() as db:
        assert db.get(Run, tag_run) is None
        assert not db.scalars(select(Case).where(Case.source.like("test:row-lock-race:%"))).all()
        assert not db.scalars(select(Responder).where(Responder.run_id == tag_run)).all()
