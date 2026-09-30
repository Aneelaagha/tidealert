import uuid
from typing import Optional

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class GaugeReading(Base):
    __tablename__ = "gauge_readings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    signal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("signals.id"), nullable=False)

    usgs_site_id: Mapped[str] = mapped_column(String, nullable=False)
    stage_ft: Mapped[float] = mapped_column(Float, nullable=False)
    discharge_cfs: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    datum: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    flood_stage_ft: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    moderate_stage_ft: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    major_stage_ft: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    signal: Mapped["Signal"] = relationship("Signal", back_populates="gauge_readings")
