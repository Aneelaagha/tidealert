from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DataSource
from app.models.data_source import SignalType


def ensure_data_source(
    db: Session,
    *,
    name: str,
    category: str,
    cadence_seconds: int,
    stale_after_seconds: int,
    type_default: SignalType,
    url: str,
    license: str,
    notes: str | None = None,
) -> DataSource:
    """Return the data source with this name, creating or refreshing it."""
    source = db.scalar(select(DataSource).where(DataSource.name == name))
    if source is None:
        source = DataSource(name=name)
        db.add(source)
    source.category = category
    source.cadence_seconds = cadence_seconds
    source.stale_after_seconds = stale_after_seconds
    source.type_default = type_default
    source.url = url
    source.license = license
    source.notes = notes
    db.flush()
    return source
