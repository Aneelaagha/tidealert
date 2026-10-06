"""Relief needs and pledges: test pledges, no payments. See app.services.relief_needs."""
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Run
from app.services import map_state, relief_needs
from app.services.relief_needs import ReliefError

router = APIRouter(prefix="/relief", tags=["relief"])


class PostNeed(BaseModel):
    run_id: uuid.UUID
    zone_id: uuid.UUID
    item_type: str
    quantity_needed: int
    created_by: str  # who is posting (free text: there is no authentication yet)
    at: Optional[datetime] = None  # the slider time the zone's access state is read at


class PostPledge(BaseModel):
    quantity: int
    at: Optional[datetime] = None


class At(BaseModel):
    at: Optional[datetime] = None


def _run(db: Session, run_id) -> Run:
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


def _when(run: Run, at: Optional[datetime]) -> datetime:
    try:
        return map_state.resolve_at(run, at)
    except map_state.TimeOutOfWindow as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _do(db: Session, fn):
    try:
        out = fn()
        db.commit()
        return out
    except ReliefError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get("/needs")
def get_board(run_id: uuid.UUID, at: Optional[datetime] = None, db: Session = Depends(get_db)):
    """The run's needs with each zone's access state at `at`, most urgent first."""
    run = _run(db, run_id)
    return relief_needs.board(db, run, _when(run, at))


@router.post("/needs", status_code=201)
def post_need(body: PostNeed, db: Session = Depends(get_db)):
    run = _run(db, body.run_id)
    when = _when(run, body.at)
    return _do(db, lambda: relief_needs.one(db, relief_needs.post_need(db, run, body.zone_id, body.item_type, body.quantity_needed, body.created_by), when))


@router.post("/needs/{need_id}/pledges", status_code=201)
def pledge(need_id: uuid.UUID, body: PostPledge, db: Session = Depends(get_db)):
    def go():
        need = relief_needs.pledge(db, need_id, body.quantity)
        return relief_needs.one(db, need, _when(db.get(Run, need.run_id), body.at))
    return _do(db, go)


@router.post("/needs/{need_id}/close")
def close(need_id: uuid.UUID, body: At = At(), db: Session = Depends(get_db)):
    def go():
        need = relief_needs.close_need(db, need_id)
        return relief_needs.one(db, need, _when(db.get(Run, need.run_id), body.at))
    return _do(db, go)
