"""The needs board API: what operators say each zone needs, and entering it. See app.services.needs."""
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Run
from app.models.need_event import NeedEventKind
from app.models.pledge import PledgeClose
from app.models.zone_need import ItemType
from app.services import map_state, needs, pledges
from app.services.needs import NeedError

router = APIRouter(tags=["needs"])


class NeedEntry(BaseModel):
    run_id: uuid.UUID
    zone_id: uuid.UUID
    item_type: ItemType
    event: NeedEventKind
    quantity: int
    actor: str  # who is entering this (free text: there is no authentication yet)
    at: Optional[datetime] = None  # event time on the run's clock; default: end of a scenario's window, now if live
    note: str = ""


class PledgeOffer(BaseModel):
    run_id: uuid.UUID
    zone_id: uuid.UUID
    item_type: ItemType
    quantity: int
    donor: str  # a display name typed by the donor; no contact details are kept
    at: Optional[datetime] = None
    note: str = ""


class PledgeClosing(BaseModel):
    kind: PledgeClose
    actor: str  # who is closing it (free text: there is no authentication yet)
    at: Optional[datetime] = None
    note: str = ""


def _run(db: Session, run_id: uuid.UUID) -> Run:
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/needs")
def get_needs(run_id: uuid.UUID, at: Optional[datetime] = None, db: Session = Depends(get_db)):
    """Every zone's operator-entered needs as of `at`, with each open need's zone access and a run summary."""
    run = _run(db, run_id)
    try:
        when = map_state.resolve_at(run, at)
    except map_state.TimeOutOfWindow as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return needs.needs_as_of(db, run, when)


@router.post("/needs", status_code=201)
def enter_need(body: NeedEntry, db: Session = Depends(get_db)):
    """Enter, fulfil or withdraw a need. Refused on a replay. Returns the zone's needs as of the entry's time."""
    run = _run(db, body.run_id)
    try:
        row = needs.record(db, run, body.zone_id, body.item_type, body.event, body.quantity, body.actor, body.at,
                           body.note)
        state = needs.zone_state(db, run, body.zone_id, row.at)
    except NeedError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    db.commit()
    return {"run_id": str(run.id), "zone_id": str(body.zone_id), "at": row.at.isoformat(), "label": needs.LABEL, **state}


@router.post("/pledges", status_code=201)
def offer_supplies(body: PledgeOffer, db: Session = Depends(get_db)):
    """A donor offers supplies against an open need. Refused on a replay. Returns the zone's needs and pledges."""
    run = _run(db, body.run_id)
    try:
        row = pledges.offer(db, run, body.zone_id, body.item_type, body.quantity, body.donor, body.at, body.note)
        state = needs.zone_state(db, run, body.zone_id, row.offered_at)
    except NeedError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    db.commit()
    return {"run_id": str(run.id), "zone_id": str(body.zone_id), "at": row.offered_at.isoformat(),
            "pledge_id": str(row.id), "label": pledges.LABEL, **state}


@router.post("/pledges/{pledge_id}/close")
def close_pledge(pledge_id: uuid.UUID, body: PledgeClosing, db: Session = Depends(get_db)):
    """An operator records an offer as received (which fulfils that much of the need) or withdrawn."""
    try:
        row, run = pledges.close(db, pledge_id, body.kind, body.actor, body.at, body.note)
        state = needs.zone_state(db, run, row.zone_id, row.closed_at)
    except NeedError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    db.commit()
    return {"run_id": str(run.id), "zone_id": str(row.zone_id), "at": row.closed_at.isoformat(),
            "pledge_id": str(row.id), "label": pledges.LABEL, **state}
