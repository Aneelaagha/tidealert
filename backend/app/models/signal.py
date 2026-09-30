import uuid
from datetime import datetime, timezone
from typing import Optional

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, Enum, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.data_source import SignalType


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_sources.id"), nullable=False
    )

    signal_type: Mapped[SignalType] = mapped_column(Enum(SignalType, name="signal_type"), nullable=False)
    variable: Mapped[str] = mapped_column(String, nullable=False)
    value_num: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    value_text: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Any geometry type (point report, polygon extent, etc.).
    geometry: Mapped[Optional[str]] = mapped_column(Geometry(geometry_type="GEOMETRY", srid=4326), nullable=True)

    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    corroborates_signal_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("signals.id"), nullable=True
    )
    conflicts_with_signal_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("signals.id"), nullable=True
    )

    source: Mapped["DataSource"] = relationship("DataSource", back_populates="signals")
    corroborates: Mapped[Optional["Signal"]] = relationship(
        "Signal", remote_side=[id], foreign_keys=[corroborates_signal_id]
    )
    conflicts_with: Mapped[Optional["Signal"]] = relationship(
        "Signal", remote_side=[id], foreign_keys=[conflicts_with_signal_id]
    )
    gauge_readings: Mapped[list["GaugeReading"]] = relationship("GaugeReading", back_populates="signal")
