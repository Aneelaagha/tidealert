"""Reports built from a run's stored state, read-only. See app.services.after_action."""
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Run
from app.services import after_action, map_state

router = APIRouter(tags=["reports"])


@router.get("/reports/after-action")
def after_action_report(run_id: uuid.UUID, at: Optional[datetime] = None, db: Session = Depends(get_db)):
    """What the run flagged, when, what was done and what the system warned about, as of `at`, labelled with the run's
    mode, with the same content as Markdown (`markdown`) for download."""
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    try:
        when = map_state.resolve_at(run, at)
    except map_state.TimeOutOfWindow as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    report = after_action.build(db, run, when)
    return {**report, "markdown": after_action.to_markdown(report)}
