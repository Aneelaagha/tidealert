"""Copilot tools: read-only questions answered from the database, as of a run's time `at`.

Every value a copilot answer states comes from one of these functions; they
reuse the map's own queries (app.services.map_state), so the copilot and the
map can never disagree. They never write.

Exposure: fields the map does not show (household phone, age bracket,
disability, income, language, exact location) are never returned. Every
result reports which households its data was derived from and whether any of
them is real (households.is_synthetic is false). Real household data must
never be sent to an external model; the model path refuses such a result
(app.services.copilot).
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Case, Household, Run, Zone
from app.models.case import ConfidenceWord
from app.models.case_engine_contribution import ContributionDirection, Engine
from app.services import map_state
from app.services.confidence import FRESH, HALF_LIFE, case_confidence, effective, latest_evidence, visible

HOUSEHOLD_ENGINES = (Engine.silence, Engine.listening)  # their evidence comes from households


class NotFound(LookupError):
    pass


@dataclass
class ToolResult:
    tool: str
    run: dict  # id, name, mode
    at: datetime
    data: dict
    household_ids: set = field(default_factory=set)  # households the data was derived from
    real_household_ids: set = field(default_factory=set)  # of those, not synthetic

    @property
    def external_ok(self) -> bool:
        """May this result be sent to an external model? Only if no real household's data is in it."""
        return not self.real_household_ids


def _run_ref(run: Run) -> dict:
    return {"id": str(run.id), "name": run.name, "mode": run.mode.value, "caveats": map_state.run_summary_caveats(run)}


def _result(db: Session, tool: str, run: Run, at: datetime, data: dict, cases: list[Case]) -> ToolResult:
    ids = set()
    for case in cases:
        if case.household_id:
            ids.add(case.household_id)
        elif any(c.engine in HOUSEHOLD_ENGINES for c in case.contributions):
            # A zone Case built from household evidence (e.g. corroborated depth reports): count every household
            # in the zone, since the evidence does not link each contributing household.
            ids |= set(db.scalars(select(Household.id).where(Household.zone_id == case.zone_id)))
    real = set(db.scalars(select(Household.id).where(Household.id.in_(ids), Household.is_synthetic.is_(False)))) \
        if ids else set()
    return ToolResult(tool, _run_ref(run), at, data, ids, real)


def _run(db: Session, run_id) -> Run:
    run = db.get(Run, run_id)
    if run is None:
        raise NotFound("no such run")
    return run


def _run_cases(db: Session, run: Run, at: datetime, zone_id=None, case_id=None) -> list[Case]:
    q = (select(Case).where(Case.run_id == run.id, Case.opened_at <= at)
         .options(selectinload(Case.contributions), selectinload(Case.tasks)))
    if zone_id is not None:
        q = q.where(Case.zone_id == zone_id)
    if case_id is not None:
        q = q.where(Case.id == case_id)
    return list(db.scalars(q.order_by(Case.opened_at)))


def resolve_time(db: Session, run_id, at: Optional[datetime] = None) -> datetime:
    """The run's clock at `at` (default: end of its window), as every tool resolves it."""
    return map_state.resolve_at(_run(db, run_id), at)


# ---------------------------------------------------------------- tools
def run_overview(db: Session, run_id, at: Optional[datetime] = None) -> ToolResult:
    """The run, its clock, its sources' freshness, and counts of Cases and tasks as of `at`."""
    run = _run(db, run_id)
    at = map_state.resolve_at(run, at)
    cases = _run_cases(db, run, at)
    words: dict = {}
    for c in cases:
        w = case_confidence(c, at).word.value
        words[w] = words.get(w, 0) + 1
    tasks = map_state.cases(db, run, at)
    active = [t for c in tasks for t in c["tasks"] if t["active"]]
    data = {
        "run": map_state.run_summary(db, run), "freshness": map_state.freshness(db, run, at),
        "cases_opened": len(cases), "cases_by_confidence_word": words,
        "active_tasks": len(active),
        "active_tasks_awaiting_assignment": sum(1 for t in active if t["status"] == "pending"
                                                and not t["verify_before_dispatch"]),
        "active_tasks_flagged_verify": sum(1 for t in active if t["verify_before_dispatch"]),
    }
    return _result(db, "run_overview", run, at, data, cases)


def find_zones(db: Session, run_id, text: str, limit: int = 10) -> ToolResult:
    """Zones of the run whose name contains `text` (case-insensitive)."""
    run = _run(db, run_id)
    regions = map_state.run_regions(db, run)
    zones = db.scalars(select(Zone).where(Zone.region.in_(regions), Zone.name.ilike(f"%{text}%"))
                       .order_by(Zone.name).limit(limit)).all()
    data = {"query": text, "zones": [{"zone_id": str(z.id), "name": z.name, "region": z.region} for z in zones]}
    return ToolResult("find_zones", _run_ref(run), map_state.resolve_at(run, None), data)


def zone_status(db: Session, run_id, zone_id, at: Optional[datetime] = None) -> ToolResult:
    """One zone as of `at`: risk level (and why it reads unknown), data confidence, coverage gaps, Case and task
    summaries. Exactly what the map shows for it."""
    run = _run(db, run_id)
    at = map_state.resolve_at(run, at)
    fc = map_state.zones_geojson(db, run, at, zone_ids=[zone_id])
    if not fc["features"]:
        raise NotFound("no such zone in this run")
    props = dict(fc["features"][0]["properties"])
    props.pop("task_anchor", None)
    for g in props["coverage_gaps"]:
        g["reason"] = fc["gap_reasons"][g.pop("reason_id")]
    return _result(db, "zone_status", run, at, props, _run_cases(db, run, at, zone_id=zone_id))


def zone_cases(db: Session, run_id, zone_id, at: Optional[datetime] = None) -> ToolResult:
    """Every Case in a zone opened by `at`, with contributions and tasks as of `at`."""
    run = _run(db, run_id)
    at = map_state.resolve_at(run, at)
    cases = _run_cases(db, run, at, zone_id=zone_id)
    return _result(db, "zone_cases", run, at, {"zone_id": str(zone_id),
                                               "cases": [map_state.case_detail(c, at) for c in cases]}, cases)


def open_cases(db: Session, run_id, at: Optional[datetime] = None, limit: int = 50) -> ToolResult:
    """The run's Cases opened by `at` (status open or in progress), strongest confidence first."""
    run = _run(db, run_id)
    at = map_state.resolve_at(run, at)
    order = [ConfidenceWord.corroborated, ConfidenceWord.single_source, ConfidenceWord.stale_verify]
    cases = [c for c in _run_cases(db, run, at) if c.status.value in ("open", "in_progress")]
    rows = []
    for c in cases:
        conf = case_confidence(c, at)
        rows.append({"case_id": str(c.id), "zone_id": str(c.zone_id), "household_case": c.household_id is not None,
                     "status": c.status.value, "confidence_word": conf.word.value, "opened_at": c.opened_at,
                     "inference_sentence": c.inference_sentence,
                     "engines": sorted({x.engine.value for x in c.contributions
                                        if x.direction == ContributionDirection.supports and visible(x, at)})})
    rows.sort(key=lambda r: (order.index(ConfidenceWord(r["confidence_word"])), r["opened_at"]))
    data = {"total": len(rows), "shown": min(len(rows), limit), "cases": rows[:limit]}
    return _result(db, "open_cases", run, at, data, cases)


def explain_confidence(db: Session, run_id, case_id, at: Optional[datetime] = None) -> ToolResult:
    """Why a Case reads its confidence word as of `at`: the rule that decided it, and each contribution's
    stored and decayed confidence against the freshness threshold."""
    run = _run(db, run_id)
    at = map_state.resolve_at(run, at)
    cases = _run_cases(db, run, at, case_id=case_id)
    if not cases:
        raise NotFound("no such Case in this run as of this time")
    case = cases[0]
    conf = case_confidence(case, at)
    latest = latest_evidence(case, at)
    contribs = []
    for c in sorted((c for c in case.contributions if visible(c, at)), key=lambda c: c.first_observed_at):
        eff = effective(c, at)
        contribs.append({"engine": c.engine.value, "direction": c.direction.value,
                         "stored_confidence": round(c.engine_confidence, 3), "effective_confidence": round(eff, 3),
                         "fresh": c.direction == ContributionDirection.supports and eff >= FRESH,
                         "last_confirmed_at": min(c.observed_at, at),
                         "fragment": c.rule_fragment.split("] ", 1)[-1]})
    if conf.word == ConfidenceWord.stale_verify:
        if latest is not None and latest.direction == ContributionDirection.contradicts:
            rule = "stale_verify: the most recent evidence contradicts the Case"
        else:
            rule = f"stale_verify: no supporting contribution is still fresh (effective confidence >= {FRESH})"
    elif conf.word == ConfidenceWord.corroborated:
        rule = (f"corroborated: fresh support from {conf.fresh_sources} independent sources "
                "(two engines, or one contribution backed by several households)")
    else:
        rule = "single_source: fresh support from one source only"
    data = {
        "case_id": str(case.id), "confidence_word": conf.word.value, "rule": rule,
        "support": round(conf.support, 3), "contradiction": round(conf.contradiction, 3),
        "fresh_sources": conf.fresh_sources, "fresh_threshold": FRESH,
        "half_lives_minutes": {e.value: int(h.total_seconds() // 60) for e, h in HALF_LIFE.items()},
        "latest_evidence": None if latest is None else {"engine": latest.engine.value,
                                                        "direction": latest.direction.value},
        "contributions": contribs,
        "caveat": map_state.CONFIDENCE_CAVEAT,
    }
    return _result(db, "explain_confidence", run, at, data, [case])


def briefing_facts(db: Session, run_id, zone_id, at: Optional[datetime] = None) -> ToolResult:
    """Everything a responder briefing for one zone may state: zone status, its Cases with their latest
    evidence, its tasks, source freshness and caveats."""
    status = zone_status(db, run_id, zone_id, at)
    cases = zone_cases(db, run_id, zone_id, status.at)
    run = _run(db, run_id)
    data = {"zone": status.data, "cases": cases.data["cases"],
            "freshness": map_state.freshness(db, run, status.at)}
    result = ToolResult("briefing_facts", status.run, status.at, data,
                        status.household_ids | cases.household_ids, status.real_household_ids | cases.real_household_ids)
    return result
