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


class PledgeClose(str, enum.Enum):
    received = "received"  # an operator says the offered supplies arrived (this also fulfils that much of the need)
    withdrawn = "withdrawn"  # the offer was withdrawn or declined; the quantity goes back to the unpledged need


class Pledge(Base):
    """A donor's OFFER of supplies against an operator-entered need, in one run. An offer is a claim: nothing here
    checks it is real, moves goods or takes money, and no contact details are stored. It is open from offered_at
    until closed_at, so a past time reads what had been offered and not yet closed by then."""
    __tablename__ = "pledges"
    __table_args__ = (Index("ix_pledges_run_zone", "run_id", "zone_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE", name="fk_pledges_run_id_runs"), nullable=False)
    zone_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zones.id", ondelete="CASCADE", name="fk_pledges_zone_id_zones"), nullable=False)
    item_type: Mapped[ItemType] = mapped_column(Enum(ItemType, name="item_type", create_type=False), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    donor: Mapped[str] = mapped_column(String, nullable=False)  # a display name typed by the donor: no contact details
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    offered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # on the run's clock
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_kind: Mapped[Optional[PledgeClose]] = mapped_column(Enum(PledgeClose, name="pledge_close_kind"), nullable=True)
    closed_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # free text: there is no authentication yet
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
