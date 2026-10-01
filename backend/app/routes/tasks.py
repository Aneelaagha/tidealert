"""Tasks and responders: read as of a time, and the actions people take. See app.services.task_actions."""
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import Case, Responder, Run, Task
from app.models.task import TaskStatus
from app.services import map_state, task_actions, task_view
from app.services.task_actions import TaskActionError

router = APIRouter(tags=["tasks"])


class Action(BaseModel):
    actor: str  # who is doing this (free text: there is no authentication yet)
    at: Optional[datetime] = None  # event time on the run's clock; default: end of a scenario's window, now if live
    note: str = ""


class AssignAction(Action):
    responder_id: uuid.UUID


class StatusAction(Action):
    status: TaskStatus
    outcome: Optional[str] = None


def _get(db: Session, model, id_, what: str):
    obj = db.get(model, id_)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{what} not found")
    return obj


def _act(db: Session, fn, *args, **kwargs):
    try:
        result = fn(db, *args, **kwargs)
    except TaskActionError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    db.commit()
    return result


def _task_at(db: Session, task: Task, at: Optional[datetime]) -> dict:
    run = db.get(Run, task.case.run_id)
    try:
        when = map_state.resolve_at(run, at)
    except map_state.TimeOutOfWindow as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    state = task_view.task_state(task, when)
    if state is None:
        raise HTTPException(status_code=404, detail=f"task did not exist yet at {when.isoformat()}")
    return state


@router.get("/tasks")
def list_tasks(run_id: uuid.UUID, at: Optional[datetime] = None, active_only: bool = False,
               db: Session = Depends(get_db)):
    """The run's tasks as they stood at `at`."""
    run = _get(db, Run, run_id, "Run")
    try:
        when = map_state.resolve_at(run, at)
    except map_state.TimeOutOfWindow as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    tasks = db.scalars(select(Task).join(Case, Task.case_id == Case.id).where(Case.run_id == run.id)
                       .options(selectinload(Task.events)).order_by(Task.created_at)).all()
    states = [s for s in (task_view.task_state(t, when) for t in tasks) if s and (s["active"] or not active_only)]
    return {"run_id": str(run.id), "mode": run.mode.value, "at": when.isoformat(), "tasks": states}


@router.get("/tasks/{task_id}")
def get_task(task_id: uuid.UUID, at: Optional[datetime] = None, db: Session = Depends(get_db)):
    return _task_at(db, _get(db, Task, task_id, "Task"), at)


@router.post("/tasks/{task_id}/assign")
def assign_task(task_id: uuid.UUID, body: AssignAction, db: Session = Depends(get_db)):
    task = _get(db, Task, task_id, "Task")
    responder = _get(db, Responder, body.responder_id, "Responder")
    _act(db, task_actions.assign, task, responder, body.actor, body.at, body.note)
    return _task_at(db, task, task.events[-1].at)


@router.post("/tasks/{task_id}/status")
def set_task_status(task_id: uuid.UUID, body: StatusAction, db: Session = Depends(get_db)):
    task = _get(db, Task, task_id, "Task")
    _act(db, task_actions.set_status, task, body.status, body.actor, body.at, body.note, body.outcome)
    return _task_at(db, task, task.events[-1].at)


@router.post("/tasks/{task_id}/clear-verify")
def clear_verify(task_id: uuid.UUID, body: Action, db: Session = Depends(get_db)):
    task = _get(db, Task, task_id, "Task")
    _act(db, task_actions.clear_verify, task, body.actor, body.at, body.note)
    return _task_at(db, task, task.events[-1].at)


@router.post("/cases/{case_id}/tasks", status_code=201)
def open_follow_up(case_id: uuid.UUID, body: Action, db: Session = Depends(get_db)):
    case = _get(db, Case, case_id, "Case")
    task = _act(db, task_actions.open_follow_up, case, body.actor, body.at, body.note)
    return _task_at(db, task, task.events[-1].at)


@router.get("/responders")
def list_responders(run_id: Optional[uuid.UUID] = None, db: Session = Depends(get_db)):
    """Responders who can serve a run: its synthetic responders (scenario), or real ones (run_id omitted)."""
    q = select(Responder).order_by(Responder.name)
    q = q.where(Responder.run_id == run_id) if run_id else q.where(Responder.run_id.is_(None))
    return {"responders": [task_view.responder_view(r) for r in db.scalars(q)]}
