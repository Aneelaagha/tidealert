"""Last call: the latest moment a dispatch could still set out before each zone's roads close. See app.services.last_call."""
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Run
from app.services import last_call, map_state
from app.services.last_call import LastCallError

router = APIRouter(tags=["last-call"])


@router.get("/map/last-call")
def map_last_call(run_id: uuid.UUID, at: Optional[datetime] = None, reply_min: int = 0, decision_min: int = 0, travel_min: int = 0,
                  db: Session = Depends(get_db)):
    """Each flagged zone's last call as of `at`, for the lead time (reply + decision + travel, in minutes) you set."""
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    try:
        when = map_state.resolve_at(run, at)
    except map_state.TimeOutOfWindow as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    try:
        return last_call.board(db, run, when, reply_min, decision_min, travel_min)
    except LastCallError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
