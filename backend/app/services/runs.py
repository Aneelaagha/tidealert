"""Register runs (replay / scenario / live) and the data sources each one reads.

Every Case belongs to a run, and a run's mode is set here, explicitly, by the
script or service that produces its Cases. Nothing infers a mode from a Case
source label or from whether a view is being scrubbed through time.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DataSource, Run, RunSource
from app.models.run import RunMode


def ensure_run(db: Session, *, name: str, mode: RunMode, description: str,
               window_start: Optional[datetime], window_end: Optional[datetime],
               source_names: list[str]) -> Run:
    """Create or refresh the run with this name and add `source_names` to its sources. Sources are only added,
    never removed: a run can be swept in parts (one gauge at a time) and its other Cases still read theirs.
    Refuses to change the mode of an existing run."""
    run = db.scalar(select(Run).where(Run.name == name))
    if run is None:
        run = Run(name=name, mode=mode)
        db.add(run)
    elif run.mode != mode:
        raise ValueError(f"run {name!r} is registered as {run.mode.value}, not {mode.value}")
    run.description = description
    run.window_start, run.window_end = window_start, window_end

    have = {rs.data_source_id for rs in run.sources}
    for source_name in source_names:
        source = db.scalar(select(DataSource).where(DataSource.name == source_name))
        if source is None:
            raise ValueError(f"run {name!r}: no data source named {source_name!r}")
        if source.id not in have:
            run.sources.append(RunSource(data_source_id=source.id))
            have.add(source.id)
    db.flush()
    return run
