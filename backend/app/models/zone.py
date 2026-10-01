import enum
import uuid
from datetime import datetime
from typing import Any, Optional

from geoalchemy2 import Geometry
from sqlalchemy import Boolean, DateTime, Enum, Float, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class RiskLevel(str, enum.Enum):
    unknown = "unknown"  # not assessed: the default, never shown as safe
    safe = "safe"  # only when an engine asserts it (none does yet)
    elevated = "elevated"
    extreme = "extreme"


class Zone(Base):
    __tablename__ = "zones"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    boundary: Mapped[str] = mapped_column(Geometry(geometry_type="POLYGON", srid=4326), nullable=False)
    region: Mapped[str] = mapped_column(String, nullable=False)
    # Census block group GEOID when the zone is a block group.
    census_geoid: Mapped[Optional[str]] = mapped_column(String, nullable=True, unique=True)
    # 2020 census block group the zone mostly falls in, for zones smaller than a block group.
    block_group_geoid: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)

    silence_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    isolation_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    risk_level: Mapped[RiskLevel] = mapped_column(
        Enum(RiskLevel, name="risk_level"), default=RiskLevel.unknown, server_default=RiskLevel.unknown.value,
        nullable=False,
    )
    # When risk_level was last set (event time, not wall-clock time). Null: never set by an engine.
    risk_level_set_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    population_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    registered_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    current_water_depth: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    flood_extent_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Null = not assessed. No engine computes it yet.
    data_confidence: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    coverage_gaps: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    typical_resolution_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    last_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    households: Mapped[list["Household"]] = relationship("Household", back_populates="zone")
    needs: Mapped[list["ZoneNeed"]] = relationship("ZoneNeed", back_populates="zone")
    cases: Mapped[list["Case"]] = relationship("Case", back_populates="zone")
