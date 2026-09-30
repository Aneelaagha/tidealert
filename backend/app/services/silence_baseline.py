"""Silence engine: each household's own expected response time, and whether a response is late for them.

A probe's latency is responded_at - sent_at. Only check-in SMS count (purpose
"checkin", or unset on probes recorded before cascades existed): voice calls,
neighbor prompts and depth follow-ups have their own timing and would skew the
baseline. People differ enormously (one
household answers in a minute, another always takes 40), so "late" only
means something relative to that household's own history. That per-household
baseline is the silence engine's main false-positive reducer.

Per household, over its last WINDOW answered probes:

- median_response_seconds    median latency (stored on Household)
- response_variance_seconds  variance of latency, in seconds^2 (stored on Household)
- probe_count                every check-in SMS sent, answered or not (stored on Household)

Latencies are right-skewed, so lateness is judged on the log scale with
robust statistics:

    z = (log(elapsed) - median(log latency)) / scale
    scale = max(1.4826 * MAD(log latency), MIN_LOG_SCALE)

and a response (or the silence so far, for a probe not yet answered) is late
when z > Z_LATE, i.e. elapsed > median * exp(Z_LATE * scale). MIN_LOG_SCALE
keeps a very regular responder from being flagged for ordinary jitter.
With fewer than MIN_HISTORY answered probes there is no personal baseline and
the verdict is "insufficient_history", never "late".

Z_LATE, MIN_LOG_SCALE, WINDOW and MIN_HISTORY are statistical choices, not
calibrated against real registry data (none exists yet).

Confidence of a "late" verdict (silence_confidence) is a product of three
factors from the same data:

    history      0 below MIN_HISTORY answered check-ins (no verdict is ever "late" then),
                 else min(1, answered in window / WINDOW)
    strength     1 / (1 + exp(-(z - Z_LATE))): 0.5 at the flag threshold, ~0.95 at z = Z_LATE + 3
    reliability  1 - the household's historical never-answered rate, since silence from a household
                 that often never replies says less

The strength curve is a design choice; the product is a heuristic, not a
probability calibrated against outcomes.
"""
import math
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

import numpy as np
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Household, ProbeResponse
from app.models.probe_response import ProbeChannel, ProbePurpose

WINDOW = 30
MIN_HISTORY = 5
Z_LATE = 3.0
MIN_LOG_SCALE = math.log(1.25)  # at least +/-25% timing jitter
MAD_TO_SD = 1.4826


@dataclass
class Baseline:
    household_id: uuid.UUID
    probe_count: int
    answered: int
    median_seconds: Optional[float]
    variance_seconds2: Optional[float]
    log_median: Optional[float]
    log_scale: Optional[float]
    unanswered: int = 0  # earlier check-ins never answered (all history, not just the window)

    @property
    def sufficient(self) -> bool:
        return self.answered >= MIN_HISTORY

    @property
    def late_after_seconds(self) -> Optional[float]:
        """Elapsed time beyond which a response (or silence) counts as late for this household."""
        if not self.sufficient:
            return None
        return math.exp(self.log_median + Z_LATE * self.log_scale)


@dataclass
class Verdict:
    status: str  # "late" | "normal" | "insufficient_history"
    elapsed_seconds: float
    z: Optional[float]
    late_after_seconds: Optional[float]


def compute_baseline(household_id: uuid.UUID, latencies_seconds: Iterable[float], probe_count: int) -> Baseline:
    """Baseline from a household's answered latencies (oldest first; only the last WINDOW are used)."""
    lat = np.asarray(list(latencies_seconds), dtype=float)[-WINDOW:]
    if len(lat) == 0:
        return Baseline(household_id, probe_count, 0, None, None, None, None)
    logs = np.log(np.maximum(lat, 1.0))
    log_median = float(np.median(logs))
    scale = max(MAD_TO_SD * float(np.median(np.abs(logs - log_median))), MIN_LOG_SCALE)
    return Baseline(
        household_id=household_id,
        probe_count=probe_count,
        answered=len(lat),
        median_seconds=float(np.median(lat)),
        variance_seconds2=float(np.var(lat, ddof=1)) if len(lat) > 1 else 0.0,
        log_median=log_median,
        log_scale=scale,
    )


def evaluate(baseline: Baseline, elapsed_seconds: float) -> Verdict:
    """Is this response time (or silence so far) late for this household?"""
    if not baseline.sufficient:
        return Verdict("insufficient_history", elapsed_seconds, None, None)
    z = (math.log(max(elapsed_seconds, 1.0)) - baseline.log_median) / baseline.log_scale
    return Verdict("late" if z > Z_LATE else "normal", elapsed_seconds, z, baseline.late_after_seconds)


def checkin_sms_filter():
    """Check-in SMS: the probes the baseline (and silence) is about."""
    return (ProbeResponse.channel == ProbeChannel.sms) & or_(
        ProbeResponse.purpose.is_(None), ProbeResponse.purpose == ProbePurpose.checkin
    )


def household_baseline(db: Session, household_id: uuid.UUID, before: Optional[datetime] = None) -> Baseline:
    """Baseline from a household's check-in SMS sent before `before` (all of them if None)."""
    query = select(ProbeResponse.sent_at, ProbeResponse.responded_at).where(
        ProbeResponse.household_id == household_id, checkin_sms_filter()
    )
    if before is not None:
        query = query.where(ProbeResponse.sent_at < before)
    rows = db.execute(query.order_by(ProbeResponse.sent_at)).all()
    latencies = [(r.responded_at - r.sent_at).total_seconds() for r in rows if r.responded_at is not None]
    baseline = compute_baseline(household_id, latencies, probe_count=len(rows))
    baseline.unanswered = len(rows) - len(latencies)
    return baseline


@dataclass
class SilenceConfidence:
    value: float
    history: float
    strength: float
    reliability: float

    def describe(self) -> str:
        return (f"confidence {self.value:.2f} = history {self.history:.2f} x strength {self.strength:.2f} "
                f"x reliability {self.reliability:.2f}")


def silence_confidence(baseline: Baseline, verdict: Verdict) -> SilenceConfidence:
    """Confidence of a silence verdict (0 without a personal baseline)."""
    history = min(1.0, baseline.answered / WINDOW) if baseline.sufficient else 0.0
    strength = 1.0 / (1.0 + math.exp(-(verdict.z - Z_LATE))) if verdict.z is not None else 0.0
    reliability = 1.0 - baseline.unanswered / baseline.probe_count if baseline.probe_count else 0.0
    return SilenceConfidence(history * strength * reliability, history, strength, reliability)


def update_household_baselines(db: Session, household_ids: Optional[list[uuid.UUID]] = None) -> list[Baseline]:
    """Recompute and store median/variance/probe_count for these households (all with probes if None)."""
    if household_ids is None:
        household_ids = list(db.scalars(select(ProbeResponse.household_id).distinct()))
    baselines = []
    for hid in household_ids:
        b = household_baseline(db, hid)
        household = db.get(Household, hid)
        household.median_response_seconds = b.median_seconds
        household.response_variance_seconds = b.variance_seconds2
        household.probe_count = b.probe_count
        baselines.append(b)
    db.commit()
    return baselines
