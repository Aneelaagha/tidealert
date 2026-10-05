"""Supply access: for every zone of a run, as of a time, can a supply run reach it from the main road network?

This is route feasibility only, and it adds nothing the isolation engine has not already stored. Each zone's state is
the zone-access state responder safety uses (app.services.safety.zone_access), read for the whole run instead of for
the zones that have a task:

- reachable: a dry route to the main road network exists even if every road of unknown flooding is flooded.
- reconnected: it was cut off and the engine's latest evidence is a reconnection, the optimistic bound (roads of
  unknown flooding taken as passable). Not read as "reachable".
- possibly_isolated: cut off only if roads of unknown flooding are flooded.
- isolated: every route to the main network is flooded, even with unknown roads passable.
- not_evaluated: not assessed (a permanent coverage gap, or the engine never ran on the region). Never read as safe.

What this does not say: where a supply run would start (no depot or staging data exists, so there is no origin), how
far or how long a route is, what vehicle it suits, whether a dry road is passable (debris, damage, closures), or which
roads to take. No route-by-route flood state is stored, so no route geometry is returned.
"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Run, Zone
from app.services import map_state, safety

STATES = ("isolated", "possibly_isolated", "reconnected", "reachable", "not_evaluated")  # worst first
LABELS = {"isolated": "cut off", "possibly_isolated": "may be cut off", "reconnected": "reconnected (optimistic)",
          "reachable": "reachable", "not_evaluated": "not assessed"}
DOES_NOT_SHOW = ("Route feasibility from the main road network only. It does not show where a supply run would "
                 "start (no depot or staging data exists), distance or time, vehicle suitability, debris or damage "
                 "on a dry road, or which roads to take; no route-by-route flood state is stored. 'Reachable' means "
                 "a dry route exists even if every road of unknown flooding is flooded. 'Reconnected' is the "
                 "optimistic bound. 'Not assessed' is never a sign a zone can be reached.")


def supply_access(db: Session, run: Run, at: datetime) -> dict:
    regions = map_state.run_regions(db, run)
    people = {str(zid): pop for zid, pop in db.execute(
        select(Zone.id, Zone.population_count).where(Zone.region.in_(regions)))}
    access = safety.zone_access(db, run, at, people)
    reasons: list[str] = []
    reason_ids: dict[str, int] = {}
    zones = {}
    for zid, a in access.items():
        rid = reason_ids.setdefault(a["reason"], len(reasons))
        if rid == len(reasons):
            reasons.append(a["reason"])
        zones[zid] = {"zone_access": a["zone_access"], "since": a["since"].isoformat() if a["since"] else None,
                      "mechanism": a["mechanism"], "reason_id": rid}
    counts = {s: {"zones": 0, "population": 0} for s in STATES}
    for zid, z in zones.items():
        counts[z["zone_access"]]["zones"] += 1
        counts[z["zone_access"]]["population"] += people[zid] or 0
    return {"run_id": str(run.id), "mode": run.mode.value, "at": at.isoformat(), "states": list(STATES),
            "labels": LABELS, "counts": counts, "reasons": reasons, "zones": zones, "does_not_show": DOES_NOT_SHOW}
