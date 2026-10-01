"""What people do with tasks: assign, move through statuses, clear a verify flag, open a follow-up task.

The engine only creates and flags tasks (app.services.task_rules); everything
here is a person's action. Rules:

- Replay runs are read-only: their tasks show what the engines would have
  created, and an assignment in 2017 would invent a dispatch history (422).
- Actions happen at an event time `at` on the run's clock: inside a scenario's
  window (default: its end), now for a live run. It may not be earlier than
  the task's latest event.
- A task flagged verify_before_dispatch cannot be assigned until a person
  clears the flag (409).
- A responder must belong to the task's run (a synthetic responder of that
  scenario), or be a real responder for a live run, and be available (one
  active task at a time).
- Assigning sets the Case to in_progress. Completing a task never resolves
  the Case: that stays a separate human decision.
- Closing a task (complete / unable_to_reach / cancelled) frees the responder
  and leaves the Case without an active task. The engine creates a new task
  only on new evidence (task_rules R1); a person can open a follow-up.
- No authentication yet: `actor` is free text.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Case, Responder, Run, Task
from app.models.case import CaseStatus
from app.models.responder import ResponderStatus
from app.models.run import RunMode
from app.models.task import ACTIVE_STATUSES, TaskKind, TaskPriority, TaskStatus
from app.services import map_state
from app.services.task_rules import snapshot

TRANSITIONS = {
    TaskStatus.en_route: (TaskStatus.assigned,),
    TaskStatus.complete: (TaskStatus.assigned, TaskStatus.en_route),
    TaskStatus.unable_to_reach: (TaskStatus.assigned, TaskStatus.en_route),
    TaskStatus.cancelled: (TaskStatus.pending, TaskStatus.assigned, TaskStatus.en_route),
}
CLOSED = (TaskStatus.complete, TaskStatus.unable_to_reach, TaskStatus.cancelled)


class TaskActionError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


def _run_of(db: Session, case: Case) -> Run:
    return db.get(Run, case.run_id)


def _writable(run: Run) -> None:
    if run.mode == RunMode.replay:
        raise TaskActionError(422, f"run {run.name!r} is a replay: its tasks show what the engines would have "
                                   "created; assigning or changing them would invent a dispatch history")


def _actor(actor: str) -> str:
    actor = (actor or "").strip()
    if not actor:
        raise TaskActionError(422, "actor is required (who is doing this; there is no authentication yet)")
    return actor


def _when(run: Run, task: Optional[Task], at: Optional[datetime]) -> datetime:
    try:
        when = map_state.resolve_at(run, at)
    except map_state.TimeOutOfWindow as exc:
        raise TaskActionError(422, str(exc))
    if task is not None and task.events and when < task.events[-1].at:
        raise TaskActionError(422, f"at {when.isoformat()} is before the task's latest event "
                                   f"({task.events[-1].at.isoformat()})")
    return when


def assign(db: Session, task: Task, responder: Responder, actor: str, at: Optional[datetime] = None,
           note: str = "") -> Task:
    case = task.case
    run = _run_of(db, case)
    _writable(run)
    actor = _actor(actor)
    when = _when(run, task, at)
    if task.status != TaskStatus.pending:
        raise TaskActionError(409, f"task is {task.status.value}; only a pending task can be assigned "
                                   "(cancel it and open a follow-up to reassign)")
    if task.verify_before_dispatch:
        raise TaskActionError(409, f"verify before dispatch: {task.verify_reason}. Clear the flag first.")
    if responder.run_id != case.run_id and not (responder.run_id is None and run.mode == RunMode.live):
        raise TaskActionError(422, "responder does not belong to this run (synthetic responders serve only "
                                   "their own scenario; real responders only live runs)")
    if responder.status != ResponderStatus.available:
        raise TaskActionError(409, f"responder {responder.name!r} is {responder.status.value}")
    task.status, task.assigned_responder_id, task.assigned_at = TaskStatus.assigned, responder.id, when
    responder.status = ResponderStatus.assigned
    if case.status == CaseStatus.open:
        case.status = CaseStatus.in_progress
    snapshot(task, when, f"assigned to {responder.name}" + (f": {note}" if note else ""), actor=actor)
    return task


def set_status(db: Session, task: Task, status: TaskStatus, actor: str, at: Optional[datetime] = None,
               note: str = "", outcome: Optional[str] = None) -> Task:
    case = task.case
    run = _run_of(db, case)
    _writable(run)
    actor = _actor(actor)
    when = _when(run, task, at)
    allowed = TRANSITIONS.get(status)
    if allowed is None:
        raise TaskActionError(422, f"cannot set status {status.value} directly (use assign for 'assigned')")
    if task.status not in allowed:
        raise TaskActionError(409, f"task is {task.status.value}; {status.value} needs one of "
                                   + ", ".join(s.value for s in allowed))
    task.status = status
    if status == TaskStatus.en_route:
        task.started_at = when
    if status in CLOSED:
        task.completed_at = when
        task.outcome = outcome or task.outcome
        if task.assigned_responder is not None:
            task.assigned_responder.status = ResponderStatus.available
        if case.task_id == task.id or case.task is task:
            case.task = None  # no active task; the Case itself stays as it is (resolving it is a person's call)
    snapshot(task, when, status.value + (f": {note}" if note else "") + (f" (outcome: {outcome})" if outcome else ""),
             actor=actor)
    return task


def clear_verify(db: Session, task: Task, actor: str, at: Optional[datetime] = None, note: str = "") -> Task:
    """A person has looked at the conflicting or stale evidence and decides the task may be dispatched.
    Priority goes back to what it was before the flag (from the task's history)."""
    run = _run_of(db, task.case)
    _writable(run)
    actor = _actor(actor)
    when = _when(run, task, at)
    if task.status not in ACTIVE_STATUSES or not task.verify_before_dispatch:
        raise TaskActionError(409, "task is not an active task flagged verify_before_dispatch")
    before = [e for e in task.events if not e.verify_before_dispatch]
    restored = before[-1].priority if before else TaskPriority.medium
    task.verify_before_dispatch, task.verify_reason, task.verify_cleared_at = False, None, when
    task.priority, task.priority_reason = restored, f"restored after verification by {actor}"
    snapshot(task, when, "verify flag cleared" + (f": {note}" if note else ""), actor=actor)
    return task


def open_follow_up(db: Session, case: Case, actor: str, at: Optional[datetime] = None, note: str = "") -> Task:
    """A person opens a new task on a Case that has no active task (e.g. after unable_to_reach)."""
    run = _run_of(db, case)
    _writable(run)
    actor = _actor(actor)
    when = _when(run, None, at)
    if case.task is not None and case.task.status in ACTIVE_STATUSES:
        raise TaskActionError(409, "the Case already has an active task")
    if when < case.opened_at:
        raise TaskActionError(422, "at is before the Case opened")
    task = Task(case=case, status=TaskStatus.pending, verify_before_dispatch=False, verify_cleared_at=when,
                kind=TaskKind.welfare_check if case.household_id else TaskKind.reach_block,
                priority=TaskPriority.medium, priority_reason=f"follow-up opened by {actor}",
                created_by_rule=f"manual: follow-up by {actor}", created_at=when)
    case.task = task
    snapshot(task, when, "follow-up opened; pending, awaiting assignment" + (f": {note}" if note else ""), actor=actor)
    return task
