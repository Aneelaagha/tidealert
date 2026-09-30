import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict


class GaugeReadingBase(BaseModel):
    signal_id: uuid.UUID
    usgs_site_id: str
    stage_ft: float
    discharge_cfs: Optional[float] = None
    datum: Optional[str] = None
    flood_stage_ft: Optional[float] = None
    moderate_stage_ft: Optional[float] = None
    major_stage_ft: Optional[float] = None


class GaugeReadingCreate(GaugeReadingBase):
    pass


class GaugeReadingUpdate(BaseModel):
    signal_id: Optional[uuid.UUID] = None
    usgs_site_id: Optional[str] = None
    stage_ft: Optional[float] = None
    discharge_cfs: Optional[float] = None
    datum: Optional[str] = None
    flood_stage_ft: Optional[float] = None
    moderate_stage_ft: Optional[float] = None
    major_stage_ft: Optional[float] = None


class GaugeReadingRead(GaugeReadingBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
