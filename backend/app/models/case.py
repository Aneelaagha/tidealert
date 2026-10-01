import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CaseStatus(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    resolved = "resolved"
    false_alarm = "false_alarm"


class ConfidenceWord(str, enum.Enum):
    corroborated = "corroborated"
    single_source = "single_source"
    stale_verify = "stale_verify"


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    zone_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zones.id"), nullable=False, index=True
    )
    household_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id"), nullable=True
    )

    status: Mapped[CaseStatus] = mapped_column(
        Enum(CaseStatus, name="case_status"), default=CaseStatus.open, nullable=False, index=True
    )
    inference_sentence: Mapped[str] = mapped_column(Text, nullable=False)
    # Where the case came from, e.g. "backtest:2017-08-25..2017-09-02:USGS-08074500" for a historical
    # replay. Null for live cases. Lets replays be replaced wholesale and kept apart from live cases.
    source: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    # The run (replay / scenario / live) that produced this case; its mode is what the map shows.
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", name="fk_cases_run_id_runs"), nullable=False, index=True)
    confidence_word: Mapped[ConfidenceWord] = mapped_column(
        Enum(ConfidenceWord, name="confidence_word"), nullable=False
    )

    # cases.task_id -> tasks and tasks.case_id -> cases form a cycle, so this
    # FK is added with ALTER TABLE after both tables exist.
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", use_alter=True, name="fk_cases_task_id_tasks"),
        nullable=True,
    )

    outcome: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    validated: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    last_contribution_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    escalated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    zone: Mapped["Zone"] = relationship("Zone", back_populates="cases")
    run: Mapped["Run"] = relationship("Run", back_populates="cases")
    household: Mapped[Optional["Household"]] = relationship("Household", back_populates="cases")
    contributions: Mapped[list["CaseEngineContribution"]] = relationship(
        "CaseEngineContribution", back_populates="case", cascade="all, delete-orphan"
    )
    # The currently active task for this case.
    task: Mapped[Optional["Task"]] = relationship("Task", foreign_keys=[task_id], post_update=True)
    # Every task ever created for this case.
    tasks: Mapped[list["Task"]] = relationship(
        "Task", foreign_keys="Task.case_id", back_populates="case"
    )
