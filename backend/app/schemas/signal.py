import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.data_source import SignalType
from app.schemas.geometry import wkb_to_geojson


class SignalBase(BaseModel):
    source_id: uuid.UUID
    signal_type: SignalType
    variable: str
    value_num: Optional[float] = None
    value_text: Optional[str] = None
    # Any GeoJSON geometry (Point, Polygon, ...).
    geometry: Optional[dict[str, Any]] = None
    observed_at: datetime
    corroborates_signal_id: Optional[uuid.UUID] = None
    conflicts_with_signal_id: Optional[uuid.UUID] = None


class SignalCreate(SignalBase):
    pass


class SignalUpdate(BaseModel):
    source_id: Optional[uuid.UUID] = None
    signal_type: Optional[SignalType] = None
    variable: Optional[str] = None
    value_num: Optional[float] = None
    value_text: Optional[str] = None
    geometry: Optional[dict[str, Any]] = None
    observed_at: Optional[datetime] = None
    corroborates_signal_id: Optional[uuid.UUID] = None
    conflicts_with_signal_id: Optional[uuid.UUID] = None


class SignalRead(SignalBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ingested_at: datetime

    @field_validator("geometry", mode="before")
    @classmethod
    def convert_geometry(cls, value: Any) -> Any:
        return wkb_to_geojson(value)
