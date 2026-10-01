"""Tasks and responders as plain data, read as of a time from the task's event history."""
from datetime import datetime
from typing import Optional

from app.models import Responder, Task
from app.models.task import ACTIVE_STATUSES


def task_state(task: Task, at: datetime) -> Optional[dict]:
    """The task as it stood at `at` (its latest event at or before it), or None if it did not exist yet."""
    events = [e for e in task.events if e.at <= at]
    if task.created_at > at or not events:
        return None
    last = events[-1]
    return {
        "id": str(task.id), "case_id": str(task.case_id), "kind": task.kind.value, "created_at": task.created_at,
        "created_by_rule": task.created_by_rule, "status": last.status.value, "priority": last.priority.value,
        "verify_before_dispatch": last.verify_before_dispatch,
        "assigned_responder_id": str(last.assigned_responder_id) if last.assigned_responder_id else None,
        "active": last.status in ACTIVE_STATUSES,
        "events": [{"at": e.at, "status": e.status.value, "priority": e.priority.value,
                    "verify_before_dispatch": e.verify_before_dispatch, "actor": e.actor, "note": e.note,
                    "assigned_responder_id": str(e.assigned_responder_id) if e.assigned_responder_id else None}
                   for e in events],
    }


def responder_view(responder: Responder) -> dict:
    return {"id": str(responder.id), "name": responder.name, "role": responder.role, "team_id": responder.team_id,
            "status": responder.status.value, "synthetic": responder.run_id is not None,
            "run_id": str(responder.run_id) if responder.run_id else None,
            "last_ping_at": responder.last_ping_at, "has_location": responder.last_ping_geometry is not None}
