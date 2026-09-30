"""Hourly river-stage series for the isolation engine, built from stored signals.

Stage (ft, gauge datum = 0 ft NAVD88, so stage == water-surface elevation at
the gauge) comes from three places, in order of trust:

1. "observed":  USGS measured gage height, linearly interpolated when there is
   a measured value within MAX_INTERP_GAP on both sides of the hour.
2. "rating":    where the gauge did not record stage, USGS discharge (measured
   or ESTIMATED) interpolated to the hour and converted to stage through a
   rating curve fitted to this event's own measured (discharge, stage) pairs.
3. "nwm":       NWM discharge converted through the same rating curve. Used
   only for the separate NWM-driven run, never mixed into the observed series.

The rating curve ignores hysteresis (rising and falling limbs share a curve)
and above the highest measured pair it extrapolates in log-discharge.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DataSource, Signal
from app.models.data_source import SignalType

MAX_INTERP_GAP = timedelta(minutes=30)
USGS_SOURCE = "USGS 08074500 continuous"
NWM_SOURCE = "NWM v2.1 retrospective CHRTOUT"


@dataclass
class HourlyStage:
    times: list[datetime]
    stage_ft: np.ndarray
    provenance: list[str]  # "observed" | "rating" | "nwm"


@dataclass
class RatingCurve:
    """Monotone stage-discharge relation, interpolated in log(discharge)."""

    log_q: np.ndarray
    stage_ft: np.ndarray

    @classmethod
    def fit(cls, discharge_cfs: np.ndarray, stage_ft: np.ndarray) -> "RatingCurve":
        order = np.argsort(discharge_cfs)
        q, h = discharge_cfs[order], stage_ft[order]
        # Enforce monotonicity: stage never decreases as discharge increases.
        h = np.maximum.accumulate(h)
        log_q, idx = np.unique(np.log(q), return_index=True)
        return cls(log_q=log_q, stage_ft=h[idx])

    def __call__(self, discharge_cfs: np.ndarray) -> np.ndarray:
        x = np.log(np.maximum(discharge_cfs, 1.0))
        h = np.interp(x, self.log_q, self.stage_ft)
        # Linear extrapolation in log(q) above the highest measured pair.
        slope = (self.stage_ft[-1] - self.stage_ft[-2]) / (self.log_q[-1] - self.log_q[-2])
        above = x > self.log_q[-1]
        h[above] = self.stage_ft[-1] + slope * (x[above] - self.log_q[-1])
        return h


def _series(db: Session, source: str, variable: str, measured_only: bool = False) -> tuple[np.ndarray, np.ndarray]:
    query = (
        select(Signal.observed_at, Signal.value_num)
        .join(DataSource, Signal.source_id == DataSource.id)
        .where(DataSource.name == source, Signal.variable == variable)
        .order_by(Signal.observed_at)
    )
    if measured_only:
        query = query.where(Signal.signal_type == SignalType.measured)
    rows = db.execute(query).all()
    times = np.array([r[0].timestamp() for r in rows])
    values = np.array([r[1] for r in rows], dtype=float)
    return times, values


def fit_event_rating(db: Session) -> RatingCurve:
    """Rating curve from timestamps with both a measured stage and a measured discharge."""
    h_t, h = _series(db, USGS_SOURCE, "gage_height_ft", measured_only=True)
    q_t, q = _series(db, USGS_SOURCE, "discharge_cfs", measured_only=True)
    common, h_idx, q_idx = np.intersect1d(h_t, q_t, return_indices=True)
    return RatingCurve.fit(q[q_idx], h[h_idx])


def hourly_times(start: datetime, end: datetime) -> list[datetime]:
    times, t = [], start
    while t <= end:
        times.append(t)
        t += timedelta(hours=1)
    return times


def observed_stage(db: Session, times: list[datetime], rating: RatingCurve) -> HourlyStage:
    h_t, h = _series(db, USGS_SOURCE, "gage_height_ft", measured_only=True)
    q_t, q = _series(db, USGS_SOURCE, "discharge_cfs")  # includes ESTIMATED values
    gap = MAX_INTERP_GAP.total_seconds()

    stages, provenance = [], []
    for t in times:
        ts = t.timestamp()
        i = np.searchsorted(h_t, ts)
        before_ok = i > 0 and ts - h_t[i - 1] <= gap
        after_ok = i < len(h_t) and h_t[i] - ts <= gap
        if i < len(h_t) and h_t[i] == ts:
            stages.append(h[i])
            provenance.append("observed")
        elif before_ok and after_ok:
            stages.append(float(np.interp(ts, h_t, h)))
            provenance.append("observed")
        else:
            stages.append(float(rating(np.array([np.interp(ts, q_t, q)]))[0]))
            provenance.append("rating")
    return HourlyStage(times=times, stage_ft=np.array(stages), provenance=provenance)


def nwm_stage(db: Session, times: list[datetime], rating: RatingCurve) -> HourlyStage:
    q_t, q = _series(db, NWM_SOURCE, "streamflow_cfs")
    ts = np.array([t.timestamp() for t in times])
    return HourlyStage(times=times, stage_ft=rating(np.interp(ts, q_t, q)), provenance=["nwm"] * len(times))
