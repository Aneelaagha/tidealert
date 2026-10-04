import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.zone import Zone
from app.schemas.zone import ZoneRead

# Read-only: zones are written by the engines (scripts), never through the API (app.services.data_policy).
router = APIRouter(prefix="/zones", tags=["zones"])


@router.get("/", response_model=List[ZoneRead])
def list_zones(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return db.query(Zone).offset(skip).limit(limit).all()


@router.get("/{zone_id}", response_model=ZoneRead)
def get_zone(zone_id: uuid.UUID, db: Session = Depends(get_db)):
    zone = db.get(Zone, zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail="Zone not found")
    return zone
