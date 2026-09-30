"""Generate synthetic probe/response history for testing the silence engine's per-household baseline.

There is no live household registry yet, so this creates clearly labelled
synthetic data: one zone in region "synthetic:silence-baseline" holding
N_HOUSEHOLDS test households, each with its own response habit (a log-normal
latency with its own median and spread, plus a share of probes it never
answers), and PROBES_PER_HOUSEHOLD SMS probes over the last DAYS days.

Everything is seeded and has deterministic ids; a rerun replaces the
synthetic zone, its households and their probes. Nothing outside the
synthetic zone is touched.

Usage (from the repo root):
    .venv/bin/python scripts/generate_synthetic_probes.py
"""
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from geoalchemy2.shape import from_shape  # noqa: E402
from shapely.geometry import box  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Household, ProbeResponse, Zone  # noqa: E402
from app.models.household import AgeBracket  # noqa: E402
from app.models.probe_response import ProbeChannel  # noqa: E402

REGION = "synthetic:silence-baseline"
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "tidealert:synthetic:silence-baseline")
SEED = 20170827
N_HOUSEHOLDS = 24
PROBES_PER_HOUSEHOLD = 40
DAYS = 60
# Probes are generated up to this time; demo probes come after it.
HISTORY_END = datetime(2026, 9, 1, tzinfo=timezone.utc)


@dataclass
class Profile:
    label: str
    median_seconds: float  # typical latency
    log_sd: float  # spread of log latency
    no_answer_rate: float


# Two named households the demo relies on, then a varied population.
FAST = Profile("fast responder (median ~90 s)", 90, 0.35, 0.05)
SLOW = Profile("slow responder (median ~40 min)", 2400, 0.35, 0.10)


def household_id(i: int) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"household-{i}")


def profiles(rng: np.random.Generator) -> list[Profile]:
    out = [FAST, SLOW]
    for i in range(2, N_HOUSEHOLDS):
        median = float(np.exp(rng.uniform(np.log(45), np.log(3600))))  # 45 s .. 1 h
        out.append(Profile(f"population #{i}", median, float(rng.uniform(0.25, 0.6)), float(rng.uniform(0, 0.2))))
    return out


def probe_times(rng: np.random.Generator) -> list[datetime]:
    """Probes on random days at random daytime hours (08:00-21:00 UTC-ish), oldest first."""
    start = HISTORY_END - timedelta(days=DAYS)
    days = np.sort(rng.choice(DAYS, size=PROBES_PER_HOUSEHOLD, replace=True))
    return [start + timedelta(days=int(d), hours=float(rng.uniform(8, 21))) for d in days]


def main() -> None:
    rng = np.random.default_rng(SEED)
    zone_id = uuid.uuid5(NAMESPACE, "zone")
    with SessionLocal() as db:
        ids = list(db.scalars(select(Household.id).where(Household.zone_id == zone_id)))
        if ids:
            db.execute(delete(ProbeResponse).where(ProbeResponse.household_id.in_(ids)))
            db.execute(delete(Household).where(Household.id.in_(ids)))
        db.execute(delete(Zone).where(Zone.id == zone_id))
        db.flush()

        now = datetime.now(timezone.utc)
        db.add(Zone(id=zone_id, name="Synthetic probe-test zone", region=REGION,
                    boundary=from_shape(box(0, 0, 0.001, 0.001), srid=4326), last_updated_at=now))
        db.flush()
        n_probes = n_answered = 0
        for i, prof in enumerate(profiles(rng)):
            hid = household_id(i)
            db.add(Household(id=hid, zone_id=zone_id, latitude=0.0005, longitude=0.0005,
                             age_bracket=AgeBracket.age_18_64, primary_language="en", is_registered=True))
            db.flush()
            for j, sent in enumerate(probe_times(rng)):
                answered = rng.random() >= prof.no_answer_rate
                latency = float(np.exp(rng.normal(np.log(prof.median_seconds), prof.log_sd)))
                db.add(ProbeResponse(
                    id=uuid.uuid5(NAMESPACE, f"probe-{i}-{j}"), household_id=hid, channel=ProbeChannel.sms,
                    sent_at=sent, responded_at=sent + timedelta(seconds=latency) if answered else None,
                    response_code="OK" if answered else None,
                ))
                n_probes += 1
                n_answered += answered
            print(f"  household {str(hid)[:8]}  {prof.label:34s} median {prof.median_seconds:7.0f} s  "
                  f"log-sd {prof.log_sd:.2f}  no-answer {prof.no_answer_rate:.0%}")
        db.commit()
    print(f"Wrote synthetic zone {str(zone_id)[:8]} ({REGION}): {N_HOUSEHOLDS} households, {n_probes} probes, "
          f"{n_answered} answered")


if __name__ == "__main__":
    main()
