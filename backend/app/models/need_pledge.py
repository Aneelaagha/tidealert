import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NeedPledge(Base):
    """One pledge against a relief need: a quantity and when it was entered. Deliberately NO identity columns (no name,
    contact, IP or session): a pledge is an anonymous, unverified test entry."""
    __tablename__ = "need_pledges"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_need_pledges_quantity_positive"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    need_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zone_needs.id", ondelete="CASCADE", name="fk_need_pledges_need_id_zone_needs"), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    need: Mapped["ZoneNeed"] = relationship("ZoneNeed", back_populates="pledges")
