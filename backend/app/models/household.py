import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AgeBracket(str, enum.Enum):
    under_18 = "under_18"
    age_18_64 = "18_64"
    age_65_plus = "65_plus"


class SignalSource(str, enum.Enum):
    social = "social"
    sms = "sms"
    mesh = "mesh"
    radio = "radio"
    none = "none"


class HouseholdStatus(str, enum.Enum):
    unknown = "unknown"
    safe = "safe"
    needs_help = "needs_help"
    isolated = "isolated"
    rescued = "rescued"


class Household(Base):
    __tablename__ = "households"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    zone_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zones.id"), nullable=False, index=True
    )

    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)

    age_bracket: Mapped[AgeBracket] = mapped_column(Enum(AgeBracket, name="age_bracket"), nullable=False)
    has_disability: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    primary_language: Mapped[str] = mapped_column(String, nullable=False)
    income_bracket: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    is_registered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # True only for generated test households. Default false: a household nobody marked counts as REAL, and real
    # household data is never sent to an external service (app.services.copilot checks this before any model call).
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    contact_phone: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    registered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    last_signal_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_signal_source: Mapped[SignalSource] = mapped_column(
        Enum(SignalSource, name="signal_source"), default=SignalSource.none, nullable=False
    )
    current_silence_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)

    status: Mapped[HouseholdStatus] = mapped_column(
        Enum(HouseholdStatus, name="household_status"), default=HouseholdStatus.unknown, nullable=False
    )

    # Neighbor who can be probed on this household's behalf.
    nominee_household_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id"), nullable=True
    )

    median_response_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    response_variance_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    probe_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    zone: Mapped["Zone"] = relationship("Zone", back_populates="households")
    nominee: Mapped[Optional["Household"]] = relationship("Household", remote_side=[id])
    cases: Mapped[list["Case"]] = relationship("Case", back_populates="household")
    probe_responses: Mapped[list["ProbeResponse"]] = relationship("ProbeResponse", back_populates="household")
