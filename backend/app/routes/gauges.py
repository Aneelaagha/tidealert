"""Current gauge readings, read-only. See app.services.gauge_readings."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import gauge_readings

router = APIRouter(tags=["gauges"])


@router.get("/gauges/current")
def current_gauges(db: Session = Depends(get_db)):
    """The latest USGS readings for the project's gauges with their freshness, or an honest "unavailable"."""
    return gauge_readings.current(db)
