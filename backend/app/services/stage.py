"""Stage series for the isolation engine, built from stored USGS signals for one gauge.

Stage (ft above gauge datum) at each engine timestep comes from, in order of
trust:

1. "observed": USGS measured gage height, linearly interpolated when there is
   a measured value within MAX_INTERP_GAP on both sides of the timestep.
2. "rating":   where the gauge did not record stage, USGS discharge (measured
   or ESTIMATED) interpolated to the timestep and converted to stage through
   a rating curve fitted to this event's own measured (discharge, stage)
   pairs.

The rating curve ignores hysteresis (rising and falling limbs share a curve)
and above the highest measured pair it extrapolates in log-discharge.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DataSource, Signal
from app.models.data_source import SignalType

MAX_INTERP_GAP = timedelta(minutes=30)


def usgs_source_name(site_id: str) -> str:
    return f"USGS {site_id} continuous"


@dataclass
class StageSeries:
    times: list[datetime]
    stage_ft: np.ndarray
    provenance: list[str]  # "observed" | "rating"

    def first_crossing(self, threshold_ft: float) -> Optional[datetime]:
        """First time stage reaches the threshold, interpolated between timesteps."""
        above = np.flatnonzero(self.stage_ft >= threshold_ft)
        if len(above) == 0:
            return None
        i = above[0]
        if i == 0:
            return self.times[0]
        h0, h1 = self.stage_ft[i - 1], self.stage_ft[i]
        frac = (threshold_ft - h0) / (h1 - h0)
        return self.times[i - 1] + (self.times[i] - self.times[i - 1]) * frac


@dataclass
class RatingCurve:
    """Monotone stage-discharge relation, interpolated in log(discharge)."""

    log_q: np.ndarray
    stage_ft: np.ndarray

    @classmethod
    def fit(cls, discharge_cfs: np.ndarray, stage_ft: np.ndarray) -> "RatingCurve":
        keep = discharge_cfs > 0
        order = np.argsort(discharge_cfs[keep])
        q, h = discharge_cfs[keep][order], stage_ft[keep][order]
        # Enforce monotonicity: stage never decreases as discharge increases.
        h = np.maximum.accumulate(h)
        log_q, idx = np.unique(np.log(q), return_index=True)
        return cls(log_q=log_q, stage_ft=h[idx])

    def __call__(self, discharge_cfs: np.ndarray) -> np.ndarray:
        x = np.log(np.maximum(np.asarray(discharge_cfs, dtype=float), 1e-3))
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


def fit_event_rating(db: Session, site_id: str) -> RatingCurve:
    """Rating curve from timestamps with both a measured stage and a measured discharge."""
    source = usgs_source_name(site_id)
    h_t, h = _series(db, source, "gage_height_ft", measured_only=True)
    q_t, q = _series(db, source, "discharge_cfs", measured_only=True)
    _, h_idx, q_idx = np.intersect1d(h_t, q_t, return_indices=True)
    if len(h_idx) < 2:
        raise RuntimeError(f"USGS {site_id}: fewer than 2 paired stage/discharge observations for a rating curve")
    return RatingCurve.fit(q[q_idx], h[h_idx])


def timesteps(start: datetime, end: datetime, step: timedelta) -> list[datetime]:
    times, t = [], start
    while t <= end:
        times.append(t)
        t += step
    return times


def observed_stage(db: Session, site_id: str, times: list[datetime], rating: RatingCurve) -> StageSeries:
    source = usgs_source_name(site_id)
    h_t, h = _series(db, source, "gage_height_ft", measured_only=True)
    q_t, q = _series(db, source, "discharge_cfs")  # includes ESTIMATED values
    gap = MAX_INTERP_GAP.total_seconds()

    stages, provenance = [], []
    for t in times:
        ts = t.timestamp()
        i = np.searchsorted(h_t, ts)
        exact = i < len(h_t) and h_t[i] == ts
        before_ok = i > 0 and ts - h_t[i - 1] <= gap
        after_ok = i < len(h_t) and h_t[i] - ts <= gap
        if exact or (before_ok and after_ok):
            stages.append(float(np.interp(ts, h_t, h)))
            provenance.append("observed")
        else:
            stages.append(float(rating(np.array([np.interp(ts, q_t, q)]))[0]))
            provenance.append("rating")
    return StageSeries(times=times, stage_ft=np.array(stages), provenance=provenance)
