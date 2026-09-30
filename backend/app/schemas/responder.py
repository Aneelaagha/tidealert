import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.responder import ResponderStatus
from app.schemas.geometry import wkb_to_geojson


class ResponderBase(BaseModel):
    name: str
    role: str
    team_id: Optional[str] = None
    phone: Optional[str] = None
    last_ping_at: Optional[datetime] = None
    # GeoJSON Point
    last_ping_geometry: Optional[dict[str, Any]] = None
    status: ResponderStatus = ResponderStatus.available


class ResponderCreate(ResponderBase):
    pass


class ResponderUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    team_id: Optional[str] = None
    phone: Optional[str] = None
    last_ping_at: Optional[datetime] = None
    last_ping_geometry: Optional[dict[str, Any]] = None
    status: Optional[ResponderStatus] = None


class ResponderRead(ResponderBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID

    @field_validator("last_ping_geometry", mode="before")
    @classmethod
    def convert_geometry(cls, value: Any) -> Any:
        return wkb_to_geojson(value)
