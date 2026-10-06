import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ItemType(str, enum.Enum):
    blankets = "blankets"
    food = "food"
    water = "water"
    medical = "medical"
    shelter = "shelter"
    boat = "boat"
    vehicle = "vehicle"
    other = "other"


# Goods only: what the relief board accepts (app.services.relief_needs). The enum above keeps its other values because
# the needs board and donation portal (need_events, pledges) share it.
RELIEF_ITEMS = ("water", "food", "shelter", "blankets", "medical")


class ReliefStatus(str, enum.Enum):
    open = "open"  # nothing pledged yet
    partial = "partial"  # some pledged, some still open
    filled = "filled"  # pledged equals needed: no more can be pledged
    closed = "closed"  # a coordinator closed it


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ZoneNeed(Base):
    """A need a coordinator posted for one zone in one run: so many of one item, and how many have been PLEDGED against it.
    A pledge is an unverified test entry: nothing here moves money or goods, and nothing tracks a delivery."""
    __tablename__ = "zone_needs"
    __table_args__ = (
        CheckConstraint("quantity_needed > 0", name="ck_zone_needs_needed_positive"),
        CheckConstraint("quantity_pledged >= 0", name="ck_zone_needs_pledged_not_negative"),
        CheckConstraint("quantity_pledged <= quantity_needed", name="ck_zone_needs_pledged_within_needed"),
        CheckConstraint("item_type IN ('water', 'food', 'shelter', 'blankets', 'medical')", name="ck_zone_needs_goods_only"),
        CheckConstraint("status <> 'filled' OR quantity_pledged = quantity_needed", name="ck_zone_needs_filled_means_full"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE", name="fk_zone_needs_run_id_runs"), nullable=False, index=True)
    zone_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zones.id"), nullable=False)

    item_type: Mapped[ItemType] = mapped_column(Enum(ItemType, name="item_type", create_type=False), nullable=False)
    quantity_needed: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_pledged: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    status: Mapped[ReliefStatus] = mapped_column(Enum(ReliefStatus, name="relief_status"), default=ReliefStatus.open, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)  # free text: there is no authentication yet
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    zone: Mapped["Zone"] = relationship("Zone", back_populates="needs")
    pledges: Mapped[list["NeedPledge"]] = relationship("NeedPledge", back_populates="need", cascade="all, delete-orphan")
