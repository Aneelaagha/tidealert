import uuid
from datetime import date
from typing import Optional

from sqlalchemy import Date, Float, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class NfipClaim(Base):
    __tablename__ = "nfip_claims"
    # county_fips is the leading column, so this also serves county-only lookups.
    __table_args__ = (Index("ix_nfip_claims_county_fips_date_of_loss", "county_fips", "date_of_loss"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    community_id_number: Mapped[str] = mapped_column(String, nullable=False)
    county_fips: Mapped[str] = mapped_column(String, nullable=False)
    # 12-digit census block group GEOID reported by OpenFEMA; joins claims to zones.
    census_geoid: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    date_of_loss: Mapped[date] = mapped_column(Date, nullable=False)
    flood_zone: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    amount_paid_building: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    amount_paid_contents: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
