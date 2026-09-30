import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.probe_response import DepthReported, ProbeChannel


class ProbeResponseBase(BaseModel):
    signal_id: Optional[uuid.UUID] = None
    household_id: uuid.UUID
    channel: ProbeChannel
    sent_at: datetime
    responded_at: Optional[datetime] = None
    response_code: Optional[str] = None
    response_text: Optional[str] = None
    depth_reported: Optional[DepthReported] = None
    is_corroborating: bool = False


class ProbeResponseCreate(ProbeResponseBase):
    pass


class ProbeResponseUpdate(BaseModel):
    signal_id: Optional[uuid.UUID] = None
    household_id: Optional[uuid.UUID] = None
    channel: Optional[ProbeChannel] = None
    sent_at: Optional[datetime] = None
    responded_at: Optional[datetime] = None
    response_code: Optional[str] = None
    response_text: Optional[str] = None
    depth_reported: Optional[DepthReported] = None
    is_corroborating: Optional[bool] = None


class ProbeResponseRead(ProbeResponseBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
