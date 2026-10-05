import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.zone_need import ItemType


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NeedEventKind(str, enum.Enum):
    requested = "requested"  # an operator says this much of an item is needed in the zone
    fulfilled = "fulfilled"  # an operator says this much of it was delivered
    withdrawn = "withdrawn"  # an operator says this much is no longer needed


class NeedEvent(Base):
    """One entry on the needs board: what an OPERATOR says a zone needs, in one run. Entered by a person, never
    measured or inferred. Append-only: a zone's needs at a time are summed from the events up to that time, so the
    history stays visible and a past time reads what had been entered by then."""
    __tablename__ = "need_events"
    __table_args__ = (Index("ix_need_events_run_zone_at", "run_id", "zone_id", "at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE", name="fk_need_events_run_id_runs"), nullable=False)
    zone_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zones.id", ondelete="CASCADE", name="fk_need_events_zone_id_zones"), nullable=False)
    item_type: Mapped[ItemType] = mapped_column(Enum(ItemType, name="item_type", create_type=False), nullable=False)
    event: Mapped[NeedEventKind] = mapped_column(Enum(NeedEventKind, name="need_event_kind"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    actor: Mapped[str] = mapped_column(String, nullable=False)  # free text: there is no authentication yet
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # event time on the run's clock
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
