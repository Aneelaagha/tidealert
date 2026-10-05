"""Freshness counts only a source's own kind of observation (app.services.map_state.freshness): an ESTIMATED gauge
value (stored as inferred) is not a reading, and must not make a gauge whose feed has stopped look fresh."""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.database import engine as db_engine
from app.models import DataSource, Run, RunSource, Signal
from app.models.data_source import SignalType
from app.models.run import RunMode
from app.services import map_state

T0 = datetime(2030, 1, 1, tzinfo=timezone.utc)


def _freshness_with(signals, type_default):
    connection = db_engine.connect()
    outer = connection.begin()
    db = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        src = DataSource(name="test gauge (freshness)", category="river_gauge", cadence_seconds=900,
                         stale_after_seconds=3600, type_default=type_default, url="n/a", license="n/a")
        run = Run(name="test:freshness", mode=RunMode.scenario, description="test", window_start=T0,
                  window_end=T0 + timedelta(days=1))
        db.add_all([src, run])
        db.flush()
        db.add(RunSource(run_id=run.id, data_source_id=src.id))
        for minutes, kind in signals:
            db.add(Signal(source_id=src.id, observed_at=T0 + timedelta(minutes=minutes), variable="discharge_cfs",
                          value_num=1.0, signal_type=kind))
        db.flush()
        return map_state.freshness(db, run, T0 + timedelta(hours=6))["sources"][0]["status"]
    finally:
        db.close()
        outer.rollback()
        connection.close()


def test_an_estimated_value_does_not_make_a_dead_gauge_look_fresh():
    # Last real reading 5 h before; an ESTIMATED value 10 min before.
    assert _freshness_with([(60, SignalType.measured), (350, SignalType.inferred)], SignalType.measured) == "stale"


def test_a_model_source_still_counts_its_own_inferred_values():
    assert _freshness_with([(350, SignalType.inferred)], SignalType.inferred) == "fresh"
