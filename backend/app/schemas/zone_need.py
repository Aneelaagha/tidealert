import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.zone_need import ItemType, NeedStatus


class ZoneNeedBase(BaseModel):
    zone_id: uuid.UUID
    item_type: ItemType
    quantity_needed: int
    quantity_fulfilled: int = 0
    status: NeedStatus = NeedStatus.open


class ZoneNeedCreate(ZoneNeedBase):
    pass


class ZoneNeedUpdate(BaseModel):
    zone_id: Optional[uuid.UUID] = None
    item_type: Optional[ItemType] = None
    quantity_needed: Optional[int] = None
    quantity_fulfilled: Optional[int] = None
    status: Optional[NeedStatus] = None


class ZoneNeedRead(ZoneNeedBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
