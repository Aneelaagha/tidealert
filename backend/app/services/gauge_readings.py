"""Current gauge readings: the latest values USGS has published for the gauges this project uses, as a read-only view.

This is NOT a live run. Nothing here feeds the engines, nothing is stored, and no Case, task or zone depends on it. It is
a look at what USGS says right now, so that a person can see the river the replays were built on and how fresh the
newest reading is. Every value is fetched from USGS's OGC API (the same service the ingest uses) at request time, with
the time it was observed and the time it was fetched; a reading that cannot be fetched is shown as unavailable and
never replaced by an older or estimated one.

Freshness uses the stale-after rule stored for each source (data_sources.stale_after_seconds): a reading older than that
is stale. A gauge with no stored rule reads "unknown", not fresh.
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DataSource

OGC = "https://api.waterdata.usgs.gov/ogcapi/v0/collections/continuous/items"
SITES = ("08074500", "08076000", "08075770", "03451500", "03451000")  # Houston: White Oak, Greens, Hunting. Asheville: French Broad, Swannanoa
PARAMETERS = {"00065": "gage height", "00060": "discharge"}
TIMEOUT_SECONDS = 8
CACHE_SECONDS = 60  # one fetch per minute at most: the page can be opened repeatedly without hammering USGS
DATA = Path(__file__).resolve().parent.parent / "data"

_cache: dict = {"at": 0.0, "body": None}


def _name(site: str) -> str:
    return json.loads((DATA / f"usgs-{site}" / "backtest.json").read_text())["name"]


def _fetch_one(site: str, parameter: str, get: Callable) -> dict:
    """The newest reading of one parameter at one gauge, or {"error": ...}."""
    try:
        r = get(OGC, params={"f": "json", "monitoring_location_id": f"USGS-{site}", "parameter_code": parameter,
                             "limit": 1, "sortby": "-time"}, timeout=TIMEOUT_SECONDS)
        r.raise_for_status()
        feats = r.json().get("features", [])
        if not feats:
            return {"error": "USGS returned no reading"}
        p = feats[0]["properties"]
        return {"value": float(p["value"]), "unit": p.get("unit_of_measure"), "observed_at": p["time"],
                "approval": p.get("approval_status"), "qualifier": p.get("qualifier")}
    except Exception as exc:  # network, HTTP error, or an unexpected body: say so, never guess
        return {"error": f"{type(exc).__name__}: {str(exc)[:120]}"}


def current(db: Session, now: Optional[datetime] = None, get: Optional[Callable] = None, use_cache: bool = True) -> dict:
    get = get or requests.get  # looked up at call time, so a test (or a proxy setup) can replace it
    if use_cache and _cache["body"] is not None and time.monotonic() - _cache["at"] < CACHE_SECONDS:
        return _cache["body"]
    fetched = now or datetime.now(timezone.utc)
    stale_after = {s.name: s.stale_after_seconds for s in db.scalars(select(DataSource).where(DataSource.name.like("USGS % continuous")))}
    jobs = [(site, code) for site in SITES for code in PARAMETERS]
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = dict(zip(jobs, pool.map(lambda j: _fetch_one(j[0], j[1], get), jobs)))
    gauges = []
    for site in SITES:
        readings = {PARAMETERS[c]: results[(site, c)] for c in PARAMETERS}
        times = [datetime.fromisoformat(x["observed_at"]) for x in readings.values() if "observed_at" in x]
        newest = max(times) if times else None
        age = int((fetched - newest).total_seconds()) if newest else None
        limit = stale_after.get(f"USGS {site} continuous")
        status = "unavailable" if newest is None else "unknown" if limit is None else "stale" if age > limit else "fresh"
        gauges.append({"site": site, "name": _name(site), "readings": readings, "newest_observed_at": newest.isoformat() if newest else None,
                       "age_seconds": age, "status": status, "stale_after_seconds": limit})
    ok = [g for g in gauges if g["status"] != "unavailable"]
    errors = sorted({x["error"] for g in gauges for x in g["readings"].values() if "error" in x})
    body = {"label": "Current readings. Not a live run: nothing here feeds the engines, and nothing is stored.",
            "available": bool(ok), "fetched_at": fetched.isoformat(), "source": OGC,
            "reason": None if ok else ("USGS could not be reached or returned nothing for any gauge: " + ("; ".join(errors) or "no detail")),
            "gauges": gauges}
    if use_cache:
        _cache.update(at=time.monotonic(), body=body)
    return body
