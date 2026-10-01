"""Map state for one run as of a time `at`: zones, their Cases, coverage gaps and source freshness.

Everything here is read from the database; the map adds no values of its own.

- Time: `at` is the run's clock (a replay or scenario is read back at any tick
  of its window; a live run at the current time). Cases opened after `at` and
  contributions first observed after `at` are invisible; case confidence is
  recomputed as of `at` (app.services.confidence).
- risk_level is the stored zone value, which has no history: only the latest
  value and when it was set (risk_level_set_at) are known. As of an `at` before
  it was set, or in a replay/scenario when its time was never recorded, the
  zone reads "unknown" with a note, never a value from its future.
- Case status has no history either: it is the current status.
- Zones in view are those of the regions the run's Cases are in; zones with no
  Case are returned too, so a block with no signal is shown, not omitted.
"""
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, selectinload

from app.models import Case, Run, RunSource, Signal, Zone
from app.models.case import ConfidenceWord
from app.models.case_engine_contribution import ContributionDirection, Engine
from app.models.run import RunMode
from app.models.zone import RiskLevel
from app.services.confidence import case_confidence, effective, visible

SIMPLIFY_DEG = 0.00002  # ~2 m: zone outlines lose vertices, not shape (2.5 MB -> 1.5 MB for all zones)
# Strongest first: a zone with several Cases is styled by its strongest confidence word (all are listed).
WORD_PRIORITY = [ConfidenceWord.corroborated, ConfidenceWord.single_source, ConfidenceWord.stale_verify]
CAVEATS = {
    RunMode.replay: ("Replayed from the published record, which includes values estimated after the event; a live "
                     "system would only have had provisional data at the time."),
    RunMode.scenario: "Synthetic households and scripted replies, not real people or a real event.",
    RunMode.live: "No live data sources are connected yet.",
}
CONFIDENCE_CAVEAT = ("Confidence values and words are unvalidated heuristics, not calibrated against outcomes "
                     "(docs/algorithms/confidence.md).")


class TimeOutOfWindow(ValueError):
    pass


def resolve_at(run: Run, at: Optional[datetime]) -> datetime:
    """The time to read the run at: `at` if given (must lie in a replay/scenario window), else the window's end
    (replay, scenario) or now (live)."""
    if at is not None and at.tzinfo is None:
        raise TimeOutOfWindow("at must include a timezone, e.g. 2017-08-27T18:30:00Z")
    if run.mode == RunMode.live:
        return at or datetime.now(timezone.utc)
    if at is None:
        return run.window_end
    if not (run.window_start <= at <= run.window_end):
        raise TimeOutOfWindow(f"at {at.isoformat()} is outside run {run.name!r} "
                              f"({run.window_start.isoformat()} .. {run.window_end.isoformat()})")
    return at


def run_regions(db: Session, run: Run) -> list[str]:
    return list(db.scalars(select(Zone.region).join(Case, Case.zone_id == Zone.id)
                           .where(Case.run_id == run.id).distinct().order_by(Zone.region)))


def run_summary(db: Session, run: Run) -> dict:
    regions = run_regions(db, run)
    extent = None
    if regions:
        box = db.execute(select(func.ST_XMin(func.ST_Extent(Zone.boundary)), func.ST_YMin(func.ST_Extent(Zone.boundary)),
                                func.ST_XMax(func.ST_Extent(Zone.boundary)), func.ST_YMax(func.ST_Extent(Zone.boundary)))
                         .where(Zone.region.in_(regions))).one()
        extent = [float(v) for v in box]
    sources = db.scalars(select(RunSource).where(RunSource.run_id == run.id)
                         .options(selectinload(RunSource.data_source))).all()
    return {
        "id": str(run.id), "name": run.name, "mode": run.mode.value, "description": run.description,
        "window_start": run.window_start, "window_end": run.window_end,
        "case_count": db.scalar(select(func.count()).select_from(Case).where(Case.run_id == run.id)),
        "regions": regions, "extent": extent,
        "sources": [{"name": rs.data_source.name, "category": rs.data_source.category,
                     "cadence_seconds": rs.data_source.cadence_seconds,
                     "stale_after_seconds": rs.stale_after_override_seconds or rs.data_source.stale_after_seconds,
                     "stale_after_overridden": rs.stale_after_override_seconds is not None}
                    for rs in sorted(sources, key=lambda rs: rs.data_source.name)],
        "caveats": [CAVEATS[run.mode], CONFIDENCE_CAVEAT],
    }


def vocabulary(db: Session) -> dict:
    """Every value the map can be styled by, from the enums and the stored coverage gaps, for the legend."""
    gap_kinds = sorted(db.scalars(text("SELECT DISTINCT jsonb_object_keys(coverage_gaps) FROM zones "
                                       "WHERE coverage_gaps IS NOT NULL")))
    return {
        "risk_level": [v.value for v in RiskLevel], "confidence_word": [v.value for v in ConfidenceWord],
        "engine": [v.value for v in Engine], "direction": [v.value for v in ContributionDirection],
        "mode": [v.value for v in RunMode], "coverage_gap": gap_kinds,
    }


# ---------------------------------------------------------------- cases
def _cases_at(db: Session, run: Run, at: datetime, zone_id=None) -> list[Case]:
    q = (select(Case).where(Case.run_id == run.id, Case.opened_at <= at)
         .options(selectinload(Case.contributions)).order_by(Case.opened_at))
    if zone_id is not None:
        q = q.where(Case.zone_id == zone_id)
    return list(db.scalars(q))


def case_detail(case: Case, at: datetime) -> dict:
    conf = case_confidence(case, at)
    contributions = sorted((c for c in case.contributions if visible(c, at)), key=lambda c: c.first_observed_at)
    return {
        "id": str(case.id), "zone_id": str(case.zone_id),
        "household_id": str(case.household_id) if case.household_id else None,
        "status": case.status.value, "inference_sentence": case.inference_sentence, "opened_at": case.opened_at,
        "confidence_word": conf.word.value, "support": round(conf.support, 3),
        "contradiction": round(conf.contradiction, 3), "fresh_sources": conf.fresh_sources,
        "engines": sorted({c.engine.value for c in contributions if c.direction == ContributionDirection.supports}),
        "contributions": [{
            "engine": c.engine.value, "direction": c.direction.value, "rule_fragment": c.rule_fragment,
            "engine_confidence": round(c.engine_confidence, 3), "effective_confidence": round(effective(c, at), 3),
            "independent_sources": c.independent_sources, "first_observed_at": c.first_observed_at,
            "last_confirmed_at": min(c.observed_at, at),
        } for c in contributions],
    }


def cases(db: Session, run: Run, at: datetime, zone_id=None) -> list[dict]:
    return [case_detail(c, at) for c in _cases_at(db, run, at, zone_id)]


# ---------------------------------------------------------------- zones
def _risk_as_of(zone_row, run: Run, at: datetime) -> tuple[str, Optional[str]]:
    stored, set_at = zone_row.risk_level, zone_row.risk_level_set_at
    if stored == RiskLevel.unknown:
        return RiskLevel.unknown.value, None
    if set_at is None:
        if run.mode == RunMode.live:
            return stored.value, None
        return RiskLevel.unknown.value, f"stored {stored.value}, but when it was set is not recorded"
    if set_at > at:
        return RiskLevel.unknown.value, f"set to {stored.value} at {set_at.isoformat()}, after this time"
    return stored.value, None


def _gaps(coverage_gaps: Optional[dict], at: datetime, reasons: dict) -> list[dict]:
    """A zone's coverage gaps as of `at`. Reason texts repeat across thousands of zones, so each is stored once in
    `reasons` (text -> index) and referenced by reason_id."""
    out = []
    for kind, value in (coverage_gaps or {}).items():
        if isinstance(value, dict):
            since = value.get("earliest_possible_isolation_at")
            since_dt = datetime.fromisoformat(since) if since else None
            status, reason, active = value.get("status"), value.get("reason") or "", since_dt is None or since_dt <= at
        else:
            since, status, reason, active = None, None, str(value), True
        # time_bound: starts at `since` (e.g. possibly isolated from a stage onward); otherwise permanent (e.g.
        # isolation not evaluated for a block cut off from the network even with every road dry).
        out.append({"kind": kind, "status": status, "since": since, "time_bound": since is not None, "active": active,
                    "reason_id": reasons.setdefault(reason, len(reasons))})
    return out


@dataclass
class _ZoneCases:
    count: int = 0
    word: Optional[ConfidenceWord] = None
    engines: frozenset = frozenset()


def zones_geojson(db: Session, run: Run, at: datetime, bbox: Optional[list[float]] = None) -> dict:
    regions = run_regions(db, run)
    per_zone: dict = {}
    for case in _cases_at(db, run, at):
        detail = case_confidence(case, at)
        z = per_zone.setdefault(case.zone_id, _ZoneCases())
        z.count += 1
        if z.word is None or WORD_PRIORITY.index(detail.word) < WORD_PRIORITY.index(z.word):
            z.word = detail.word
        z.engines = z.engines | {c.engine.value for c in case.contributions
                                 if c.direction == ContributionDirection.supports and visible(c, at)}

    geom = func.ST_AsGeoJSON(func.ST_SimplifyPreserveTopology(Zone.boundary, SIMPLIFY_DEG), 6)
    q = select(Zone.id, Zone.name, Zone.region, Zone.population_count, Zone.risk_level, Zone.risk_level_set_at,
               Zone.data_confidence, Zone.coverage_gaps, geom).where(Zone.region.in_(regions)).order_by(Zone.id)
    if bbox:
        q = q.where(Zone.boundary.op("&&")(func.ST_MakeEnvelope(*bbox, 4326)))
    features, reasons = [], {}
    for row in db.execute(q):
        risk, risk_note = _risk_as_of(row, run, at)
        gaps = _gaps(row.coverage_gaps, at, reasons)
        zc = per_zone.get(row.id, _ZoneCases())
        features.append({"type": "Feature", "id": str(row.id), "geometry": json.loads(row[-1]), "properties": {
            "zone_id": str(row.id), "name": row.name, "region": row.region, "population": row.population_count,
            "risk_level": risk, "risk_level_note": risk_note,
            "data_confidence": row.data_confidence,  # null = not assessed
            "coverage_gaps": gaps, "coverage_gap_active": any(g["active"] for g in gaps),
            "case_count": zc.count, "confidence_word": zc.word.value if zc.word else None,
            "engines": sorted(zc.engines),
            **{f"engine_{e.value}": e.value in zc.engines for e in Engine},
        }})
    return {"type": "FeatureCollection", "run_id": str(run.id), "mode": run.mode.value, "at": at.isoformat(),
            "gap_reasons": list(reasons), "features": features}


# ---------------------------------------------------------------- freshness
def freshness(db: Session, run: Run, at: datetime) -> dict:
    """Per source the run reads: its last observation at or before `at` and whether that is stale.

    stale:        at - last observation > stale_after (the run's override, else the source's own)
    no_data:      nothing observed yet as of `at`
    event_driven: cadence 0 (e.g. household replies): silence from it is not an outage, so it is reported
                  with its age but never judged fresh or stale
    """
    rows = db.scalars(select(RunSource).where(RunSource.run_id == run.id)
                      .options(selectinload(RunSource.data_source))).all()
    sources = []
    for rs in sorted(rows, key=lambda rs: rs.data_source.name):
        src = rs.data_source
        stale_after = rs.stale_after_override_seconds or src.stale_after_seconds
        last = db.scalar(select(func.max(Signal.observed_at)).where(Signal.source_id == src.id, Signal.observed_at <= at))
        age = (at - last).total_seconds() if last else None
        if last is None:
            status = "no_data"
        elif src.cadence_seconds == 0:
            status = "event_driven"
        else:
            status = "stale" if age > stale_after else "fresh"
        sources.append({"name": src.name, "category": src.category, "status": status, "last_observed_at": last,
                        "age_seconds": age, "stale_after_seconds": stale_after,
                        "stale_after_overridden": rs.stale_after_override_seconds is not None,
                        "cadence_seconds": src.cadence_seconds})
    note = None if sources else ("This run reads no data source recorded as signals (e.g. check-in replies are "
                                 "probe responses), so freshness is not tracked for it.")
    return {"run_id": str(run.id), "mode": run.mode.value, "at": at.isoformat(), "sources": sources,
            "summary": {s: sum(1 for x in sources if x["status"] == s) for s in ("fresh", "stale", "no_data", "event_driven")},
            "note": note, "caveats": [CAVEATS[run.mode]]}
