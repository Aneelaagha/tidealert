import uuid
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.schemas.geometry import wkb_to_geojson


class RoadSegmentBase(BaseModel):
    osm_way_id: int
    # GeoJSON LineString, e.g. {"type": "LineString", "coordinates": [[lon, lat], ...]}
    geometry: dict[str, Any]
    highway_class: str
    is_bridge: bool = False
    is_tunnel: bool = False
    graph_edge_id: Optional[str] = None


class RoadSegmentCreate(RoadSegmentBase):
    pass


class RoadSegmentUpdate(BaseModel):
    osm_way_id: Optional[int] = None
    geometry: Optional[dict[str, Any]] = None
    highway_class: Optional[str] = None
    is_bridge: Optional[bool] = None
    is_tunnel: Optional[bool] = None
    graph_edge_id: Optional[str] = None


class RoadSegmentRead(RoadSegmentBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID

    @field_validator("geometry", mode="before")
    @classmethod
    def convert_geometry(cls, value: Any) -> Any:
        return wkb_to_geojson(value)
