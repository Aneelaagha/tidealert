import enum
import uuid
from typing import Optional

from sqlalchemy import Enum, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SignalType(str, enum.Enum):
    measured = "measured"
    reported = "reported"
    inferred = "inferred"
    predicted = "predicted"


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)

    cadence_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    stale_after_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    type_default: Mapped[SignalType] = mapped_column(Enum(SignalType, name="signal_type"), nullable=False)

    url: Mapped[str] = mapped_column(String, nullable=False)
    license: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    signals: Mapped[list["Signal"]] = relationship("Signal", back_populates="source")
