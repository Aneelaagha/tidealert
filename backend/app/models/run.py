import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RunMode(str, enum.Enum):
    replay = "replay"  # a past event replayed from its recorded data (e.g. Harvey 2017)
    scenario = "scenario"  # synthetic households and scripted replies
    live = "live"  # real-time sources (none exist yet)
    mixed = "mixed"  # a real recorded event with a synthetic layer on top (e.g. synthetic responders on Harvey)


class Run(Base):
    """One replay, scenario or live deployment: the Cases it produced and the data sources it reads.

    mode is set explicitly when the run is registered; it is never inferred from the Case source label
    or from whether a view is being scrubbed through time."""

    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Stable key, e.g. "backtest:2017-08-25..2017-09-02" (the Case source labels' shared prefix).
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    mode: Mapped[RunMode] = mapped_column(Enum(RunMode, name="run_mode"), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # The clock window the run was swept over (both ends are sweep ticks). Null for a live run.
    window_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    window_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    sources: Mapped[list["RunSource"]] = relationship(
        "RunSource", back_populates="run", cascade="all, delete-orphan")
    cases: Mapped[list["Case"]] = relationship("Case", back_populates="run")


class RunSource(Base):
    """A data source a run actually reads. Many-to-many: a run can read several gauges, and a gauge can
    feed several runs."""

    __tablename__ = "run_sources"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE", name="fk_run_sources_run_id_runs"),
        primary_key=True)
    data_source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_sources.id", ondelete="CASCADE",
                                       name="fk_run_sources_data_source_id_data_sources"),
        primary_key=True)
    # Per-run staleness threshold; null means the source's own stale_after_seconds.
    stale_after_override_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    run: Mapped["Run"] = relationship("Run", back_populates="sources")
    data_source: Mapped["DataSource"] = relationship("DataSource")
