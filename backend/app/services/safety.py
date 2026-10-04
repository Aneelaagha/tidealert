"""Responder safety, zone-based: can a task's zone be reached, as of a time, and what should whoever is (or will be)
sent there be warned about. Computed from what the isolation engine already stored; nothing new is measured.

A zone's access as of `at`:
- isolated: the latest isolation evidence for the zone visible at `at` supports isolation (the engine found every
  route to the main road network flooded). It is cut off since the start of that isolation: the first "cut off"
  row after the latest reconnection, since one isolation can carry several rows as its mechanism changes; the
  mechanism shown is the latest row's. "Reachable only over flooded roads" is exactly this state; there is no
  stored route-by-route flood state to say more. Mechanism from the evidence: stranded (its own roads dry, every
  way out flooded) or submerged (every bordering road flooded).
- reconnected: the zone was isolated and the engine's latest evidence is a reconnection (a route to the main road
  network is open again, with unknown roads passable). That is the optimistic bound, so it is not read as
  "reachable": no warning, but stated with the engine's own text.
- possibly_isolated: cut off only if roads whose flooding is unknown are flooded (the zone's time-bound
  coverage gap is active).
- not_evaluated: the engine ran on the region but could not evaluate this zone (a permanent coverage gap, e.g. cut
  off from the network even with every road dry), or the engine never ran on the zone's region at all (synthetic
  scenarios: no road network, no flood source). Never read as safe.
- reachable: the engine evaluated the zone and finds a dry route even if every unknown road is flooded.

Warnings (active tasks only): the zone is cut off now; it was cut off after the task was assigned; it may be cut
off. When no responder is assigned, the after-assignment check says so instead of staying silent.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Case, Run, Zone
from app.models.case_engine_contribution import CaseEngineContribution, ContributionDirection, Engine

NOT_RUN_REASON = ("the isolation engine has not run on this zone's region (no road network or flood source), so "
                  "whether it can be reached is not assessed")
NO_ASSIGNMENT = "no assignment to warn about: no responder is assigned to this task at this time"


def _mechanism(fragment: str) -> Optional[str]:
    return "submerged" if "submerged" in fragment else "stranded" if "stranded" in fragment else None


def _fmt(t: datetime) -> str:
    return t.strftime("%Y-%m-%d %H:%M UTC")


def zone_access(db: Session, run: Run, at: datetime, zone_ids) -> dict:
    """zone_id (str) -> access as of `at`, for the given zones of the run, in two queries."""
    zone_ids = {str(z) for z in zone_ids}
    if not zone_ids:
        return {}
    zones = {str(z.id): z for z in db.scalars(select(Zone).where(Zone.id.in_(zone_ids)))}
    rows = db.execute(
        select(Case.zone_id, Zone.region, CaseEngineContribution)
        .join(CaseEngineContribution, CaseEngineContribution.case_id == Case.id)
        .join(Zone, Zone.id == Case.zone_id)
        .where(Case.run_id == run.id, CaseEngineContribution.engine == Engine.isolation)).all()
    # Regions the engine ran on in this run (it classifies every zone of a region it runs on).
    evaluated = {region for _, region, _ in rows}
    evaluated |= {z.region for z in zones.values() if isinstance((z.coverage_gaps or {}).get("isolation"), dict)}
    # Each zone's isolation evidence visible at `at`, oldest first.
    evidence: dict = {}
    for zone_id, _, c in rows:
        zid = str(zone_id)
        if zid in zone_ids and c.first_observed_at <= at and c.direction in (
                ContributionDirection.supports, ContributionDirection.contradicts):
            evidence.setdefault(zid, []).append(c)
    latest, episode_start = {}, {}
    for zid, cs in evidence.items():
        cs.sort(key=lambda c: c.first_observed_at)
        latest[zid] = cs[-1]
        # One isolation can carry several "cut off" rows (the mechanism changes, e.g. "now submerged"). It began at
        # the first of them after the latest reconnection, not at the latest one.
        start = None
        for c in cs:
            if c.direction == ContributionDirection.contradicts:
                start = None
            elif start is None:
                start = c
        episode_start[zid] = start

    out = {}
    for zid in zone_ids:
        zone = zones.get(zid)
        gap = (zone.coverage_gaps or {}).get("isolation") if zone else None
        c = latest.get(zid)
        if c is not None and c.direction == ContributionDirection.supports:
            out[zid] = {"zone_access": "isolated", "since": episode_start[zid].first_observed_at,
                        "mechanism": _mechanism(c.rule_fragment), "reason": c.rule_fragment.split("] ", 1)[-1]}
            continue
        if c is not None:  # the latest isolation evidence is a reconnection
            out[zid] = {"zone_access": "reconnected", "since": c.first_observed_at, "mechanism": None,
                        "reason": c.rule_fragment.split("] ", 1)[-1]}
            continue
        if isinstance(gap, dict) and gap.get("earliest_possible_isolation_at") and \
                datetime.fromisoformat(gap["earliest_possible_isolation_at"]) <= at:
            out[zid] = {"zone_access": "possibly_isolated",
                        "since": datetime.fromisoformat(gap["earliest_possible_isolation_at"]),
                        "mechanism": None, "reason": gap.get("reason") or ""}
        elif isinstance(gap, str):
            out[zid] = {"zone_access": "not_evaluated", "since": None, "mechanism": None, "reason": gap}
        elif zone is None or zone.region not in evaluated:
            out[zid] = {"zone_access": "not_evaluated", "since": None, "mechanism": None, "reason": NOT_RUN_REASON}
        else:
            out[zid] = {"zone_access": "reachable", "since": None, "mechanism": None,
                        "reason": "a dry route to the main road network exists even if every road of unknown "
                                  "flooding is flooded"}
    return out


def _assigned_at(task_state: dict) -> Optional[datetime]:
    """When the task's current assignee was assigned (the start of the latest run of events with that assignee)."""
    who = task_state["assigned_responder_id"]
    if not who:
        return None
    start = None
    for e in task_state["events"]:
        if e["assigned_responder_id"] == who:
            start = start or e["at"]
        else:
            start = None
    return start


def warnings_for(task_state: dict, access: dict) -> tuple[list[dict], Optional[str]]:
    """The task's warnings, and the after-assignment check's note when there is nothing to check."""
    if not task_state["active"]:
        return [], None
    kind, since = access["zone_access"], access["since"]
    assigned_at = _assigned_at(task_state)
    out = []
    if kind == "isolated":
        how = f" ({access['mechanism']})" if access["mechanism"] else ""
        if assigned_at is None:
            out.append({"code": "zone_isolated", "severity": "high", "since": since,
                        "text": f"Zone cut off{how} since {_fmt(since)}. No responder is assigned: whoever is "
                                "dispatched would be entering a cut-off area."})
        elif assigned_at < since:
            out.append({"code": "isolated_after_assignment", "severity": "high", "since": since,
                        "text": f"Zone cut off{how} at {_fmt(since)}, after the responder was assigned "
                                f"({_fmt(assigned_at)}): they may be heading into, or already in, a cut-off area."})
        else:
            out.append({"code": "zone_isolated", "severity": "high", "since": since,
                        "text": f"Zone cut off{how} since {_fmt(since)}; the responder was assigned after that "
                                f"({_fmt(assigned_at)})."})
    elif kind == "possibly_isolated":
        out.append({"code": "zone_possibly_isolated", "severity": "medium", "since": since,
                    "text": f"Zone may be cut off since {_fmt(since)}: it is isolated if roads whose flooding is "
                            "unknown are flooded."})
    return out, (NO_ASSIGNMENT if assigned_at is None and kind in ("isolated", "possibly_isolated") else None)


def attach(db: Session, run: Run, at: datetime, items: list[tuple]) -> None:
    """Add a `safety` block to each task state in `items`, a list of (zone_id, task_state). One batch per call."""
    access = zone_access(db, run, at, {z for z, _ in items})
    for zone_id, state in items:
        a = access[str(zone_id)]
        warns, note = warnings_for(state, a)
        state["safety"] = {**a, "warnings": warns, "assignment_note": note}
