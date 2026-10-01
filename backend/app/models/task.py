import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from geoalchemy2 import Geometry
from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TaskStatus(str, enum.Enum):
    pending = "pending"  # created by the case matcher; waits for a person to assign it
    assigned = "assigned"
    en_route = "en_route"
    complete = "complete"
    unable_to_reach = "unable_to_reach"  # the responder could not get there (e.g. the block is cut off)
    cancelled = "cancelled"  # a person decided it is not needed


ACTIVE_STATUSES = (TaskStatus.pending, TaskStatus.assigned, TaskStatus.en_route)


class TaskKind(str, enum.Enum):
    reach_block = "reach_block"  # a street block the engines say is cut off (or reports water)
    welfare_check = "welfare_check"  # one household: silent, asked for help, or a neighbor reports trouble


class TaskPriority(str, enum.Enum):
    """Ordinal, not a score. Design choice, not calibrated against outcomes."""
    high = "high"
    medium = "medium"
    low = "low"


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False)
    assigned_responder_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("responders.id"), nullable=True
    )

    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status"), default=TaskStatus.pending, nullable=False
    )
    kind: Mapped[TaskKind] = mapped_column(Enum(TaskKind, name="task_kind"), nullable=False)
    priority: Mapped[TaskPriority] = mapped_column(Enum(TaskPriority, name="task_priority"), nullable=False)
    priority_reason: Mapped[str] = mapped_column(Text, nullable=False)
    # Set when the Case's evidence went stale or was contradicted: check before sending anyone. Cleared if the
    # evidence becomes fresh again. Evidence never completes or cancels a task; only a person does.
    verify_before_dispatch: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false",
                                                         nullable=False)
    verify_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # When a person last cleared the flag (event time). The engine flags again only on evidence newer than this.
    verify_cleared_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_rule: Mapped[str] = mapped_column(String, nullable=False)  # the Case transition that created it
    route_geometry: Mapped[Optional[str]] = mapped_column(
        Geometry(geometry_type="LINESTRING", srid=4326), nullable=True
    )

    # Event time (the run's clock), like Case.opened_at.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    assigned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    case: Mapped["Case"] = relationship("Case", foreign_keys=[case_id], back_populates="tasks")
    assigned_responder: Mapped[Optional["Responder"]] = relationship("Responder", back_populates="tasks")
    events: Mapped[list["TaskEvent"]] = relationship(
        "TaskEvent", back_populates="task", cascade="all, delete-orphan",
        order_by=lambda: [TaskEvent.at, TaskEvent.recorded_at])


class TaskEvent(Base):
    """A snapshot of a task after each change (status, priority, verify flag, assignment), so its state can be
    read back as of any time: the latest event at or before it."""

    __tablename__ = "task_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE", name="fk_task_events_task_id_tasks"),
        nullable=False, index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # event time
    # Wall-clock insert time: orders events that share an event time (e.g. a person acting at a scenario's last tick).
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow,
                                                  server_default=func.now(), nullable=False)
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus, name="task_status"), nullable=False)
    priority: Mapped[TaskPriority] = mapped_column(Enum(TaskPriority, name="task_priority"), nullable=False)
    verify_before_dispatch: Mapped[bool] = mapped_column(Boolean, nullable=False)
    assigned_responder_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor: Mapped[str] = mapped_column(String, nullable=False)  # "engine:case_matcher", or a person (no auth yet)
    note: Mapped[str] = mapped_column(Text, nullable=False)

    task: Mapped["Task"] = relationship("Task", back_populates="events")
