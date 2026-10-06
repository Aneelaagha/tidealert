"""Candidate depots and what each can reach, as of a time. Feasibility only: see app.services.depot_reach.

The results are computed offline by scripts/depot_access.py (it rebuilds the isolation engine's inputs, writes no
database rows, and stores one file per gauge, backend/app/data/usgs-<site>/depot_access.npz). This module only reads
those files. They exist for the Harvey event, so only Harvey runs (replay or mixed) have depot access; every other
run reports that it has none.

The depots are real fire stations from OpenStreetMap (ids and fetch time recorded in each file). They are origins to
ask the question from; nothing says any of them served as a depot during Harvey.
"""
import json
from bisect import bisect_right
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Run, Zone
from app.services import run_events

DATA = Path(__file__).resolve().parent.parent / "data"
SITES = ("08074500", "08076000", "08075770")
EVENT = "Hurricane Harvey"
STATE_LABELS = {"reachable": "reachable", "only_if_unknown_roads_passable": "only if unknown roads are passable",
                "not_reachable": "not reachable", "not_evaluated": "not assessed"}
DOES_NOT_SHOW = ("Feasibility from one candidate depot only: whether a dry road route exists from the depot's road to the "
                 "zone's roads, using the isolation engine's flooded roads and its optimistic and pessimistic treatment of roads "
                 "whose flooding is unknown. It finds no route and gives no distance, time, vehicle or road capacity, and it does "
                 "not say a dry road is passable (debris, damage and closures are not modelled). The depots are real fire "
                 "stations from OpenStreetMap, used as example origins: nothing says they served as depots in Harvey. A zone in "
                 "another basin's road network is not assessed from this depot.")


@lru_cache(maxsize=None)
def _load(site: str) -> Optional[dict]:
    path = DATA / f"usgs-{site}" / "depot_access.npz"
    if not path.exists():
        return None
    d = np.load(path)
    meta = json.loads(str(d["meta"]))
    return {"meta": meta, "states": d["states"], "road_dry": d["depot_road_dry"],
            "times": [datetime.fromisoformat(t) for t in meta["times"]]}


def _all() -> list[dict]:
    return [x for x in (_load(s) for s in SITES) if x is not None]


def available(run: Run) -> bool:
    return run_events.run_event(run) == EVENT and bool(_all())


def depot_id(site: str, osm: str) -> str:
    return f"{site}:{osm}"


def list_depots(run: Run) -> dict:
    if run_events.run_event(run) != EVENT:
        return {"available": False, "reason": "Depot access is computed for the Hurricane Harvey runs only.", "depots": []}
    out = []
    for x in _all():
        m = x["meta"]
        for k, d in enumerate(m["depots"]):
            out.append({"id": depot_id(m["site"], d["osm"]), "name": d["name"], "osm": d["osm"], "lat": d["lat"], "lon": d["lon"],
                        "snapped_to_road_m": d["snap_m"], "basin": m["name"], "site": m["site"], "source": "OpenStreetMap (amenity=fire_station)",
                        "osm_fetched_at": m["osm_fetched_at"]})
    if not out:
        return {"available": False, "reason": "Depot access has not been computed (scripts/depot_access.py).", "depots": []}
    return {"available": True, "reason": None, "depots": out, "does_not_show": DOES_NOT_SHOW}


def access(db: Session, run: Run, depot: str, at: datetime) -> dict:
    """Every zone of the depot's basin network at the latest computed time step on or before `at`."""
    if not available(run):
        raise LookupError("Depot access is computed for the Hurricane Harvey runs only.")
    site = depot.split(":", 1)[0]
    x = _load(site) if site in SITES else None
    k = next((i for i, d in enumerate(x["meta"]["depots"]) if depot_id(site, d["osm"]) == depot), None) if x else None
    if x is None or k is None:
        raise LookupError(f"unknown depot {depot!r}")
    times = x["times"]
    ti = max(bisect_right(times, at) - 1, 0)
    row = x["states"][k, ti]
    zone_ids = x["meta"]["zone_ids"]
    names = {int(v): n for v, n in x["meta"]["states"].items()}
    pops = {str(z): p for z, p in db.execute(select(Zone.id, Zone.population_count).where(Zone.id.in_(zone_ids)))}
    counts = {n: {"zones": 0, "population": 0} for n in names.values()}
    for zid, code in zip(zone_ids, row):
        c = counts[names[int(code)]]
        c["zones"] += 1
        c["population"] += pops.get(zid, 0) or 0
    d = x["meta"]["depots"][k]
    return {"run_id": str(run.id), "mode": run.mode.value, "at": at.isoformat(), "tick_at": times[ti].isoformat(),
            "depot": {"id": depot, "name": d["name"], "osm": d["osm"], "lat": d["lat"], "lon": d["lon"], "snapped_to_road_m": d["snap_m"],
                      "basin": x["meta"]["name"], "road_dry": bool(x["road_dry"][k, ti])},
            "states": list(names.values()), "labels": STATE_LABELS, "counts": counts,
            "zones": {zid: names[int(code)] for zid, code in zip(zone_ids, row)},
            "engine_agreement": x["meta"].get("engine_agreement"), "does_not_show": DOES_NOT_SHOW}
