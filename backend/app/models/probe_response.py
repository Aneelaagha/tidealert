import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ProbeChannel(str, enum.Enum):
    sms = "sms"
    voice = "voice"
    neighbor = "neighbor"


class DepthReported(str, enum.Enum):
    ankle = "ankle"
    knee = "knee"
    waist = "waist"


class ProbeResponse(Base):
    __tablename__ = "probe_responses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    signal_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("signals.id"), nullable=True
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id"), nullable=False
    )

    channel: Mapped[ProbeChannel] = mapped_column(Enum(ProbeChannel, name="probe_channel"), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    responded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    response_code: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    response_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    depth_reported: Mapped[Optional[DepthReported]] = mapped_column(
        Enum(DepthReported, name="depth_reported"), nullable=True
    )
    is_corroborating: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )

    signal: Mapped[Optional["Signal"]] = relationship("Signal")
    household: Mapped["Household"] = relationship("Household", back_populates="probe_responses")
