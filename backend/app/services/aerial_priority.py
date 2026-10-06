"""Aerial priority: of the zones no road reaches, which should an aerial asset look at first? A ranking, nothing more.

Ranking rule (auditable; the only inputs are the isolation engine's recorded cut-off evidence and, off replay, the silence and
listening results already stored as Cases):

  Only zones with NO passable route are ranked: the zone's latest isolation evidence (app.services.last_call.zone_status) is a
  cut-off row at `at`. A zone that is merely "possibly" cut off, reconnected, reachable or not assessed is never ranked.
  cut_off_minutes = `at` minus the time the current run of cut-off evidence began.

  On a REPLAY run:
      order by cut_off_minutes descending (tie: zone id); score = null; silent_households = null.
      Silence is excluded: the opt-in registry did not exist in 2017, so a replay has no silence input worth ranking on.
  On a MIXED, SCENARIO or LIVE run:
      silent_households = the zone's household Cases with silence or listening evidence for the household observed by `at`
      that no later contradicting evidence has answered (null when the run holds no household in the zone: unknown stays
      unknown, it is not zero).
      score = silent_households; order by score descending (null last), tie-break cut_off_minutes descending, then zone id.

  No cell-coverage factor (no coverage data exists in this system: it is "not assessed" on every row) and no registered-household
  factor (zones.registered_count is never written, so it is not used).

What this is not: it tasks nothing, shows no feed and no aircraft, and says nothing about phones or whether anyone is in the zone.
"""
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Case, Run, Zone
from app.models.case_engine_contribution import CaseEngineContribution as C, ContributionDirection, Engine
from app.services import last_call
from app.models.run import RunMode

DEFAULT_LIMIT = 5
MAX_LIMIT = 50
NOT_ASSESSED = "cell coverage: not assessed"
CAPTION = "Ranking only. No live feed. No asset is tasked by this system."
EMPTY = "No zone meets the aerial-priority threshold at this time."
REPLAY_NOTE = "Replay: ranked by cut-off duration. Silence inputs excluded — no opt-in registry existed in 2017."
SILENCE_NOTE = "Ranked by silent households. Cell coverage not assessed."


def duration(minutes: int) -> str:
    h, m = divmod(max(minutes, 0), 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def silent_by_zone(db: Session, run: Run, at: datetime) -> tuple[dict[str, int], set[str]]:
    """(zone id -> silent household count at `at`, the zones that hold any household in this run)."""
    zones_with_households = {str(z) for (z,) in db.execute(
        select(Case.zone_id).where(Case.run_id == run.id, Case.household_id.is_not(None)).distinct())}
    rows = db.execute(
        select(Case.zone_id, Case.household_id, C.engine, C.direction, C.first_observed_at)
        .join(C, C.case_id == Case.id)
        .where(Case.run_id == run.id, Case.household_id.is_not(None), Case.opened_at <= at, C.first_observed_at <= at,
               C.engine.in_((Engine.silence, Engine.listening)))).all()
    last: dict[tuple, dict] = defaultdict(lambda: {"s": None, "c": None})
    for zid, hid, _engine, direction, t in rows:
        slot = last[(str(zid), str(hid))]
        key = "s" if direction == ContributionDirection.supports else "c"
        if slot[key] is None or t > slot[key]:
            slot[key] = t
    counts: dict[str, int] = defaultdict(int)
    for (zid, _), v in last.items():
        if v["s"] is not None and (v["c"] is None or v["c"] < v["s"]):
            counts[zid] += 1
    return dict(counts), zones_with_households


def ranking(db: Session, run: Run, at: datetime, limit: int = DEFAULT_LIMIT) -> dict:
    limit = max(1, min(limit, MAX_LIMIT))
    replay = run.mode == RunMode.replay
    ev = last_call.evidence(db, run)
    cut = {}
    for zid, events in ev.items():
        s = last_call.zone_status(events, at, timedelta(0))
        if s and s["status"] == "cut_off":
            cut[zid] = int((at - s["cutoff_at"]).total_seconds() // 60)
    names = {str(z.id): z.name for z in db.scalars(select(Zone).where(Zone.id.in_(list(cut))))} if cut else {}
    silent, with_households = ({}, set()) if replay else silent_by_zone(db, run, at)
    rows = []
    for zid, minutes in cut.items():
        n = None if replay or zid not in with_households else silent.get(zid, 0)
        frags = ["No dry route", f"Cut off {duration(minutes)}"]
        if not replay:
            frags.append("no households recorded in this run" if n is None else f"{n} silent household{'s' if n != 1 else ''}")
        frags.append(NOT_ASSESSED)
        rows.append({"zone_id": zid, "zone_name": names.get(zid, zid[:8]), "cut_off_minutes": minutes, "silent_households": n,
                     "cell_coverage_assessed": False, "score": None if replay else n, "reason_fragments": frags})
    if replay:
        rows.sort(key=lambda r: (-r["cut_off_minutes"], r["zone_id"]))
    else:
        rows.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0), -r["cut_off_minutes"], r["zone_id"]))
    for i, r in enumerate(rows[:limit], 1):
        r["rank"] = i
    return {"run_id": str(run.id), "mode": run.mode.value, "at": at.isoformat(), "silence_active": not replay,
            "available": bool(ev), "note": REPLAY_NOTE if replay else SILENCE_NOTE, "caption": CAPTION, "empty": EMPTY,
            "cut_off_zones": len(rows), "shown": min(len(rows), limit), "zones": rows[:limit],
            "reason": None if ev else "The isolation engine has not run on this run, so no zone has a cut-off time. Unknown stays unknown."}
