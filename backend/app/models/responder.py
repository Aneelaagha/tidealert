import enum
import uuid
from datetime import datetime
from typing import Optional

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ResponderStatus(str, enum.Enum):
    available = "available"
    assigned = "assigned"
    off_duty = "off_duty"


class Responder(Base):
    __tablename__ = "responders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    team_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # A responder that exists only inside one scenario run (synthetic); null = a real responder. Tasks can only be
    # assigned to responders of their own run (or real ones, for a live run).
    run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE", name="fk_responders_run_id_runs"),
        nullable=True, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    last_ping_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_ping_geometry: Mapped[Optional[str]] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326), nullable=True
    )

    status: Mapped[ResponderStatus] = mapped_column(
        Enum(ResponderStatus, name="responder_status"), default=ResponderStatus.available, nullable=False
    )

    tasks: Mapped[list["Task"]] = relationship("Task", back_populates="assigned_responder")
