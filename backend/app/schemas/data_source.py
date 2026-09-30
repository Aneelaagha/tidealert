import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.data_source import SignalType


class DataSourceBase(BaseModel):
    name: str
    category: str
    cadence_seconds: int
    stale_after_seconds: int
    type_default: SignalType
    url: str
    license: str
    notes: Optional[str] = None


class DataSourceCreate(DataSourceBase):
    pass


class DataSourceUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    cadence_seconds: Optional[int] = None
    stale_after_seconds: Optional[int] = None
    type_default: Optional[SignalType] = None
    url: Optional[str] = None
    license: Optional[str] = None
    notes: Optional[str] = None


class DataSourceRead(DataSourceBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
