"""Exercise the Listening engine end to end on synthetic households, through the case matcher.

There is no live registry or SMS/voice integration, so this builds a scripted
scenario in its own synthetic region ("synthetic:listening"): two street
blocks, households with 20 days of check-in history each (so the silence
baseline, which also decides when an SMS escalates, has something to work
with), nominated neighbors, and scripted replies:

  block A  A1 answers the SMS                       A2 misses the SMS, answers the voice call
           A3 silent; neighbor sees them OK         A4 silent; neighbor reports trouble
           A5 silent; no nominated neighbor         A6 HELP -> knee-deep
           A7 HELP -> waist-deep (corroborates A6)
  block B  B1 HELP -> ankle-deep (single report)    B2 answers the SMS

Every household gets a check-in at T0; the case matcher then sweeps every
15 minutes with the Listening engine attached. Rerunning replaces the
scenario.

Usage (from the repo root):
    .venv/bin/python scripts/listening_demo.py
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from geoalchemy2.shape import from_shape  # noqa: E402
from shapely.geometry import box  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Case, Household, ProbeResponse, Signal, Zone  # noqa: E402
from app.models.household import AgeBracket  # noqa: E402
from app.models.probe_response import DepthReported, ProbeChannel, ProbePurpose  # noqa: E402
from app.models.run import RunMode  # noqa: E402
from app.models.zone import RiskLevel  # noqa: E402
from app.services.case_matcher import CaseSweeper, ReplayClock, run_scheduler  # noqa: E402
from app.services.listening import (  # noqa: E402
    CANT_SEE, HELP, OK, SEEN_OK, TROUBLE, ListeningEngine, ScriptedReply, SimulatedTransport,
)
from app.services.runs import ensure_run  # noqa: E402
from app.services.stage import timesteps  # noqa: E402

REGION = "synthetic:listening"
NS = uuid.uuid5(uuid.NAMESPACE_URL, "tidealert:synthetic:listening")
T0 = datetime(2026, 9, 10, 14, 0, tzinfo=timezone.utc)
END = T0 + timedelta(hours=3)
SOURCE = f"replay:{T0:%Y-%m-%dT%H:%M}..{END:%H:%M}Z:{REGION}"
SEED = 7

# name, block, typical SMS reply (s), has nominee, scripted replies
SCENARIO = [
    ("A1", "A", 90, True, {(ProbePurpose.checkin, ProbeChannel.sms): ScriptedReply(timedelta(minutes=1), OK)}),
    ("A2", "A", 120, True, {(ProbePurpose.checkin, ProbeChannel.voice): ScriptedReply(timedelta(minutes=3), OK)}),
    ("A3", "A", 60, True, {(ProbePurpose.neighbor_prompt, ProbeChannel.neighbor): ScriptedReply(timedelta(minutes=10), SEEN_OK)}),
    ("A4", "A", 150, True, {(ProbePurpose.neighbor_prompt, ProbeChannel.neighbor): ScriptedReply(timedelta(minutes=12), TROUBLE)}),
    ("A5", "A", 100, False, {}),
    ("A6", "A", 80, True, {(ProbePurpose.checkin, ProbeChannel.sms): ScriptedReply(timedelta(minutes=2), HELP),
                           (ProbePurpose.depth_followup, ProbeChannel.sms): ScriptedReply(timedelta(minutes=3), "DEPTH", DepthReported.knee)}),
    ("A7", "A", 200, True, {(ProbePurpose.checkin, ProbeChannel.sms): ScriptedReply(timedelta(minutes=2), HELP),
                            (ProbePurpose.depth_followup, ProbeChannel.sms): ScriptedReply(timedelta(minutes=30), "DEPTH", DepthReported.waist)}),
    ("B1", "B", 90, True, {(ProbePurpose.checkin, ProbeChannel.sms): ScriptedReply(timedelta(minutes=2), HELP),
                           (ProbePurpose.depth_followup, ProbeChannel.sms): ScriptedReply(timedelta(minutes=4), "DEPTH", DepthReported.ankle)}),
    ("B2", "B", 90, True, {(ProbePurpose.checkin, ProbeChannel.sms): ScriptedReply(timedelta(minutes=1), OK)}),
]
BLOCKS = {"A": box(0.010, 0.010, 0.011, 0.011), "B": box(0.012, 0.010, 0.013, 0.011)}
# Unused reply code kept importable for scenarios that need it.
_ = CANT_SEE


def reset(db) -> None:
    zone_ids = list(db.scalars(select(Zone.id).where(Zone.region == REGION)))
    hh = list(db.scalars(select(Household.id).where(Household.zone_id.in_(zone_ids))))
    for case in db.scalars(select(Case).where(Case.source == SOURCE)):
        db.delete(case)
    db.flush()
    sig = [s for s in db.scalars(select(ProbeResponse.signal_id).where(ProbeResponse.household_id.in_(hh))) if s]
    db.execute(delete(ProbeResponse).where(ProbeResponse.household_id.in_(hh), ProbeResponse.parent_probe_id.is_not(None)))
    db.execute(delete(ProbeResponse).where(ProbeResponse.household_id.in_(hh)))
    db.execute(delete(Signal).where(Signal.id.in_(sig)))
    db.execute(delete(Household).where(Household.id.in_(hh)))
    db.execute(delete(Zone).where(Zone.id.in_(zone_ids)))
    db.commit()


def build(db) -> dict:
    rng = np.random.default_rng(SEED)
    now = datetime.now(timezone.utc)
    zones = {}
    for name, geom in BLOCKS.items():
        z = Zone(id=uuid.uuid5(NS, f"zone-{name}"), name=f"Synthetic listening block {name}", region=REGION,
                 boundary=from_shape(geom, srid=4326), risk_level=RiskLevel.unknown, population_count=20,
                 last_updated_at=now)
        db.add(z)
        zones[name] = z
    db.flush()
    households = {}
    for name, block, median_s, _, _ in SCENARIO:
        c = BLOCKS[block].centroid
        h = Household(id=uuid.uuid5(NS, name), zone_id=zones[block].id, latitude=c.y, longitude=c.x,
                      age_bracket=AgeBracket.age_18_64, primary_language="en", is_registered=True)
        db.add(h)
        households[name] = h
    db.flush()
    for i, (name, block, median_s, has_nominee, _) in enumerate(SCENARIO):
        h = households[name]
        if has_nominee:  # the next household in the same block
            same = [n for n, b, *_ in SCENARIO if b == block and n != name]
            h.nominee_household_id = households[same[i % len(same)]].id
        for d in range(20):  # history: answered check-ins around this household's usual reply time
            sent = T0 - timedelta(days=20 - d, hours=-float(rng.uniform(-4, 4)))
            lat = float(np.exp(rng.normal(np.log(median_s), 0.3)))
            db.add(ProbeResponse(household_id=h.id, channel=ProbeChannel.sms, purpose=ProbePurpose.checkin,
                                 sent_at=sent, responded_at=sent + timedelta(seconds=lat), response_code=OK))
    db.commit()
    return households


def main() -> None:
    with SessionLocal() as db:
        db.expire_on_commit = False
        reset(db)
        households = build(db)
        names = {h.id: n for n, h in households.items()}
        transport = SimulatedTransport(scripts={
            (households[name].id, purpose, channel): reply
            for name, _, _, _, replies in SCENARIO for (purpose, channel), reply in replies.items()})
        engine = ListeningEngine(db=db, transport=transport, household_ids=[h.id for h in households.values()])
        for h in households.values():
            engine.start_checkin(h, T0)
        db.commit()

        run = ensure_run(db, name=SOURCE, mode=RunMode.scenario, description="Synthetic households: listening engine scenario",
                         window_start=T0, window_end=END, source_names=[engine.source_name()])
        db.commit()
        sweeper = CaseSweeper(db=db, source=SOURCE, tz=timezone.utc, run_id=run.id,
                              household_zone_ids=sorted({h.zone_id for h in households.values()}), listening=engine)
        timeline = []

        def on_sweep(_, result):
            for ev in result.events:
                who = names.get(ev.household_id, "zone " + ("A" if ev.zone_id == uuid.uuid5(NS, "zone-A") else "B"))
                timeline.append(f"  {result.now:%H:%M}  {who:7s} {ev.kind:18s} {ev.detail}")

        asyncio.run(run_scheduler(ReplayClock(timesteps(T0, END, timedelta(minutes=15))), [sweeper], on_sweep))

        print(f"Timeline (sweeps every 15 min from {T0:%Y-%m-%d %H:%M} UTC; events as the sweep saw them):")
        print("\n".join(timeline))
        print("\nMessages sent:")
        for sent, channel, purpose, text in sorted(transport.outbox):
            print(f"  {sent:%H:%M}  {channel:8s} {purpose:15s} {text[:95]}")
        print("\nCases:")
        for case in sorted(db.scalars(select(Case).where(Case.source == SOURCE)), key=lambda c: c.opened_at):
            who = names.get(case.household_id, "(whole block)")
            print(f"  opened {case.opened_at:%H:%M}  {who:13s} {case.confidence_word.value:14s} {case.inference_sentence}")
            for c in sorted(case.contributions, key=lambda c: c.rule_fragment.split("]")[0] if c.rule_fragment.startswith("[") else ""):
                print(f"      {c.engine.value:9s} {c.engine_confidence}  {c.rule_fragment[:150]}")
        print("\nZones and depth reports:")
        for name in BLOCKS:
            z = db.get(Zone, uuid.uuid5(NS, f"zone-{name}"))
            reports = db.execute(select(ProbeResponse, Signal).join(Signal, Signal.id == ProbeResponse.signal_id)
                                 .join(Household, Household.id == ProbeResponse.household_id)
                                 .where(Household.zone_id == z.id)).all()
            print(f"  block {name}: risk_level {z.risk_level.value}; reports: " + "; ".join(
                f"{names[p.household_id]} {p.depth_reported.value} (signal {str(s.id)[:8]}, corroborating={p.is_corroborating}"
                f"{', corroborates ' + str(s.corroborates_signal_id)[:8] if s.corroborates_signal_id else ''})"
                for p, s in reports))


if __name__ == "__main__":
    main()
