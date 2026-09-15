import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from geoalchemy2.shape import from_shape
from shapely.geometry import shape
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.zone import Zone
from app.schemas.zone import ZoneCreate, ZoneRead, ZoneUpdate

router = APIRouter(prefix="/zones", tags=["zones"])


@router.post("/", response_model=ZoneRead, status_code=201)
def create_zone(zone_in: ZoneCreate, db: Session = Depends(get_db)):
    data = zone_in.model_dump()
    data["boundary"] = from_shape(shape(data["boundary"]), srid=4326)

    zone = Zone(**data)
    db.add(zone)
    db.commit()
    db.refresh(zone)
    return zone


@router.get("/", response_model=List[ZoneRead])
def list_zones(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return db.query(Zone).offset(skip).limit(limit).all()


@router.get("/{zone_id}", response_model=ZoneRead)
def get_zone(zone_id: uuid.UUID, db: Session = Depends(get_db)):
    zone = db.get(Zone, zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail="Zone not found")
    return zone


@router.patch("/{zone_id}", response_model=ZoneRead)
def update_zone(zone_id: uuid.UUID, zone_in: ZoneUpdate, db: Session = Depends(get_db)):
    zone = db.get(Zone, zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail="Zone not found")

    data = zone_in.model_dump(exclude_unset=True)
    if "boundary" in data:
        data["boundary"] = from_shape(shape(data["boundary"]), srid=4326)

    for field, value in data.items():
        setattr(zone, field, value)

    db.commit()
    db.refresh(zone)
    return zone


@router.delete("/{zone_id}", status_code=204)
def delete_zone(zone_id: uuid.UUID, db: Session = Depends(get_db)):
    zone = db.get(Zone, zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail="Zone not found")

    db.delete(zone)
    db.commit()
