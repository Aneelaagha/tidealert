"""Read-only map API: runs, zones as of a time, source freshness, and Cases. See app.services.map_state."""
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Run
from app.services import map_state

router = APIRouter(tags=["map"])


def _run(db: Session, run_id: uuid.UUID) -> Run:
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


def _at(run: Run, at: Optional[datetime]) -> datetime:
    try:
        return map_state.resolve_at(run, at)
    except map_state.TimeOutOfWindow as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/runs")
def list_runs(db: Session = Depends(get_db)):
    """Every run with its mode (as registered, never inferred), window, extent, sources and caveats, plus the
    values the map can be styled by."""
    runs = db.scalars(select(Run).order_by(Run.window_start)).all()
    return {"runs": [map_state.run_summary(db, r) for r in runs], "vocabulary": map_state.vocabulary(db)}


@router.get("/map/zones")
def map_zones(run_id: uuid.UUID, at: Optional[datetime] = None,
              bbox: Optional[str] = Query(None, description="min_lon,min_lat,max_lon,max_lat"),
              db: Session = Depends(get_db)):
    """GeoJSON of the run's zones as of `at` (default: end of the run's window; now for a live run)."""
    run = _run(db, run_id)
    box = None
    if bbox:
        try:
            box = [float(v) for v in bbox.split(",")]
            assert len(box) == 4
        except (ValueError, AssertionError):
            raise HTTPException(status_code=422, detail="bbox must be min_lon,min_lat,max_lon,max_lat")
    return map_state.zones_geojson(db, run, _at(run, at), box)


@router.get("/map/freshness")
def map_freshness(run_id: uuid.UUID, at: Optional[datetime] = None, db: Session = Depends(get_db)):
    run = _run(db, run_id)
    return map_state.freshness(db, run, _at(run, at))


@router.get("/cases")
def list_cases(run_id: uuid.UUID, zone_id: Optional[uuid.UUID] = None, at: Optional[datetime] = None,
               db: Session = Depends(get_db)):
    """The run's Cases opened by `at`, with their contributions visible at `at` and confidence as of `at`."""
    run = _run(db, run_id)
    at = _at(run, at)
    return {"run_id": str(run.id), "mode": run.mode.value, "at": at.isoformat(),
            "cases": map_state.cases(db, run, at, zone_id)}
