import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.task import TaskStatus
from app.schemas.geometry import wkb_to_geojson


class TaskBase(BaseModel):
    case_id: uuid.UUID
    assigned_responder_id: Optional[uuid.UUID] = None
    status: TaskStatus = TaskStatus.pending
    # GeoJSON LineString
    route_geometry: Optional[dict[str, Any]] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    outcome: Optional[str] = None


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    case_id: Optional[uuid.UUID] = None
    assigned_responder_id: Optional[uuid.UUID] = None
    status: Optional[TaskStatus] = None
    route_geometry: Optional[dict[str, Any]] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    outcome: Optional[str] = None


class TaskRead(TaskBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime

    @field_validator("route_geometry", mode="before")
    @classmethod
    def convert_geometry(cls, value: Any) -> Any:
        return wkb_to_geojson(value)
