import enum
import uuid

from sqlalchemy import Enum, Float, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Engine(str, enum.Enum):
    silence = "silence"
    isolation = "isolation"
    listening = "listening"


class CaseEngineContribution(Base):
    __tablename__ = "case_engine_contributions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False)

    engine: Mapped[Engine] = mapped_column(Enum(Engine, name="engine"), nullable=False)
    rule_fragment: Mapped[str] = mapped_column(Text, nullable=False)
    engine_confidence: Mapped[float] = mapped_column(Float, nullable=False)

    case: Mapped["Case"] = relationship("Case", back_populates="contributions")
