import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer
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


class NeedStatus(str, enum.Enum):
    open = "open"
    partially_fulfilled = "partially_fulfilled"
    fulfilled = "fulfilled"


class ZoneNeed(Base):
    __tablename__ = "zone_needs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    zone_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("zones.id"), nullable=False)

    item_type: Mapped[ItemType] = mapped_column(Enum(ItemType, name="item_type"), nullable=False)
    quantity_needed: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_fulfilled: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[NeedStatus] = mapped_column(
        Enum(NeedStatus, name="need_status"), default=NeedStatus.open, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    zone: Mapped["Zone"] = relationship("Zone", back_populates="needs")
