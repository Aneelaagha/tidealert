import uuid
from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict


class NfipClaimBase(BaseModel):
    community_id_number: str
    county_fips: str
    census_geoid: Optional[str] = None
    date_of_loss: date
    flood_zone: Optional[str] = None
    amount_paid_building: Optional[float] = None
    amount_paid_contents: Optional[float] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class NfipClaimCreate(NfipClaimBase):
    pass


class NfipClaimRead(NfipClaimBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
