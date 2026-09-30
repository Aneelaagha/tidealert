import uuid
from datetime import datetime
from typing import Any, Optional

from geoalchemy2.elements import WKBElement
from pydantic import BaseModel, ConfigDict, field_validator

from app.models.zone import RiskLevel


class ZoneBase(BaseModel):
    name: str
    # GeoJSON Polygon, e.g. {"type": "Polygon", "coordinates": [[[lon, lat], ...]]}
    boundary: dict[str, Any]
    region: str
    census_geoid: Optional[str] = None
    silence_score: float = 0
    isolation_minutes: Optional[int] = None
    risk_level: RiskLevel = RiskLevel.safe
    population_count: int = 0
    registered_count: int = 0
    current_water_depth: Optional[float] = None
    flood_extent_confirmed: bool = False
    data_confidence: int = 0
    coverage_gaps: Optional[dict[str, Any]] = None
    typical_resolution_minutes: Optional[int] = None
    last_updated_at: datetime


class ZoneCreate(ZoneBase):
    pass


class ZoneUpdate(BaseModel):
    name: Optional[str] = None
    boundary: Optional[dict[str, Any]] = None
    region: Optional[str] = None
    census_geoid: Optional[str] = None
    silence_score: Optional[float] = None
    isolation_minutes: Optional[int] = None
    risk_level: Optional[RiskLevel] = None
    population_count: Optional[int] = None
    registered_count: Optional[int] = None
    current_water_depth: Optional[float] = None
    flood_extent_confirmed: Optional[bool] = None
    data_confidence: Optional[int] = None
    coverage_gaps: Optional[dict[str, Any]] = None
    typical_resolution_minutes: Optional[int] = None
    last_updated_at: Optional[datetime] = None


class ZoneRead(ZoneBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID

    @field_validator("boundary", mode="before")
    @classmethod
    def convert_geometry(cls, value: Any) -> Any:
        if isinstance(value, WKBElement):
            from geoalchemy2.shape import to_shape
            from shapely.geometry import mapping

            return mapping(to_shape(value))
        return value
