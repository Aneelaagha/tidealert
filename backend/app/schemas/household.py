import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.household import AgeBracket, HouseholdStatus, SignalSource


class HouseholdBase(BaseModel):
    zone_id: uuid.UUID
    latitude: float
    longitude: float
    age_bracket: AgeBracket
    has_disability: bool = False
    primary_language: str
    income_bracket: Optional[str] = None
    is_registered: bool = False
    contact_phone: Optional[str] = None
    registered_at: Optional[datetime] = None
    last_signal_at: Optional[datetime] = None
    last_signal_source: SignalSource = SignalSource.none
    current_silence_score: float = 0
    status: HouseholdStatus = HouseholdStatus.unknown


class HouseholdCreate(HouseholdBase):
    pass


class HouseholdUpdate(BaseModel):
    zone_id: Optional[uuid.UUID] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    age_bracket: Optional[AgeBracket] = None
    has_disability: Optional[bool] = None
    primary_language: Optional[str] = None
    income_bracket: Optional[str] = None
    is_registered: Optional[bool] = None
    contact_phone: Optional[str] = None
    registered_at: Optional[datetime] = None
    last_signal_at: Optional[datetime] = None
    last_signal_source: Optional[SignalSource] = None
    current_silence_score: Optional[float] = None
    status: Optional[HouseholdStatus] = None


class HouseholdRead(HouseholdBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
