import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Engine(str, enum.Enum):
    silence = "silence"
    isolation = "isolation"
    listening = "listening"


class ContributionDirection(str, enum.Enum):
    supports = "supports"  # evidence for the case's claim
    contradicts = "contradicts"  # evidence against it (e.g. a reconnection, a normal reply)
    neutral = "neutral"  # informative but neither (e.g. the neighbor could not see the home)
    procedural = "procedural"  # a process step, not evidence (e.g. a voice call placed); confidence 0


class CaseEngineContribution(Base):
    __tablename__ = "case_engine_contributions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False)

    engine: Mapped[Engine] = mapped_column(Enum(Engine, name="engine"), nullable=False)
    rule_fragment: Mapped[str] = mapped_column(Text, nullable=False)
    # How strongly this contribution supports (or, for "contradicts", argues against) the case's claim when
    # it was observed, before any time decay. Decay is applied when read (app.services.confidence).
    engine_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    direction: Mapped[ContributionDirection] = mapped_column(
        Enum(ContributionDirection, name="contribution_direction"), nullable=False,
        default=ContributionDirection.supports, server_default=ContributionDirection.supports.value,
    )
    # When the engine first observed this evidence, and when it last confirmed it. Evidence an engine keeps
    # re-confirming (a block still cut off, a household still silent) is refreshed each sweep, so it decays from
    # the latest confirmation; between the two it was being confirmed every sweep. Reading a case as of an
    # earlier time needs both.
    first_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    # Independent reports behind this contribution (k households for a corroborated depth report).
    independent_sources: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    case: Mapped["Case"] = relationship("Case", back_populates="contributions")
