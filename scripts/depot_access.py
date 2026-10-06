"""Depot access for the Harvey gauges: can a candidate depot reach each zone by a dry road route, at each time step?

Feasibility only (see app.services.depot_reach): no route, distance, time or vehicle. Uses the isolation engine's own
flooded-road test and bounds, rebuilt exactly as scripts/run_isolation_pipeline.py builds them from the cached inputs
(DEM, terrain, roads) and the stored gauge record. It WRITES NO DATABASE ROWS and changes no Case, task or zone; its
output is one file per gauge, backend/app/data/usgs-<site>/depot_access.npz, plus depots.json (the candidate depots).

Candidate depots are real facilities from OpenStreetMap (fire stations inside each basin's road network), fetched from
Overpass and recorded with their OSM ids and the fetch time. They are origins to ask the question from. Nothing says
any of them served as a depot during Harvey.

Usage (from the repo root):
    .venv/bin/python scripts/depot_access.py 08074500 08076000 08075770
"""
import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import geopandas as gpd
import numpy as np
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from geoalchemy2.shape import to_shape  # noqa: E402
from shapely.geometry import Point  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Zone  # noqa: E402
from app.services import depot_reach, isolation_engine as engine  # noqa: E402
from app.services.gauge_site import resolve_gauge  # noqa: E402
from app.services.river_driver import build_river_driver, depth_over_channel, load_fim_library  # noqa: E402
from app.services.stage import fit_event_rating, observed_stage, timesteps  # noqa: E402
from app.services.street_blocks import basin_segments  # noqa: E402
from app.services.terrain import Terrain  # noqa: E402

log = logging.getLogger("depot_access")
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "backend", "app", "data")
START = datetime(2017, 8, 25, 5, tzinfo=timezone.utc)
END = datetime(2017, 9, 3, 5, tzinfo=timezone.utc)
STEP = timedelta(minutes=30)  # the page's slider ticks
OVERPASS = "https://overpass-api.de/api/interpreter"
OVERPASS_MIRRORS = (OVERPASS, "https://overpass.kumi.systems/api/interpreter", "https://overpass.private.coffee/api/interpreter")
PER_GAUGE = 3
CANDIDATES = os.path.join(os.path.dirname(__file__), "..", "backend", "app", "depot_candidates.json")


def fire_stations(bbox: tuple[float, float, float, float], cache_path: str) -> tuple[list[dict], str]:
    """OSM fire stations inside a (west, south, east, north) box, with their OSM ids, and when they were fetched. Cached
    beside the gauge's other inputs so a rerun uses exactly the same candidates (and does not depend on Overpass)."""
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            c = json.load(f)
        return c["stations"], c["fetched_at"]
    w, s, e, n = bbox
    q = f'[out:json][timeout:90];(node["amenity"="fire_station"]({s},{w},{n},{e});way["amenity"="fire_station"]({s},{w},{n},{e}););out center tags;'
    last = None
    for attempt, url in enumerate(OVERPASS_MIRRORS * 2):
        try:
            r = requests.post(url, data={"data": q}, headers={"User-Agent": "tidealert-hackathon/0.1 (depot access; contact: repo owner)"}, timeout=60)
            r.raise_for_status()
            break
        except requests.RequestException as exc:
            last = exc
            log.warning("Overpass %s failed (%s); retrying", url, exc)
            time.sleep(10 * (attempt + 1))
    else:
        raise RuntimeError(f"Overpass unavailable: {last}")
    out = []
    for el in r.json()["elements"]:
        lat, lon = (el["lat"], el["lon"]) if el["type"] == "node" else (el["center"]["lat"], el["center"]["lon"])
        out.append({"osm": f"{el['type']}/{el['id']}", "name": el.get("tags", {}).get("name") or f"Fire station {el['type']}/{el['id']}",
                    "lat": lat, "lon": lon})
    out = sorted(out, key=lambda d: d["osm"])
    fetched_at = datetime.now(timezone.utc).isoformat()
    with open(cache_path + ".tmp", "w") as f:
        json.dump({"stations": out, "fetched_at": fetched_at, "bbox": bbox, "overpass": OVERPASS, "query": "amenity=fire_station"}, f)
    os.replace(cache_path + ".tmp", cache_path)
    return out, fetched_at


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("sites", nargs="+")
    p.add_argument("--refetch", action="store_true", help="ask Overpass for fire stations again instead of using the tracked "
                   "candidates in backend/app/depot_candidates.json (which records their OSM ids and when they were fetched)")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    summary = {}
    for site_id in args.sites:
        t0 = time.time()
        site = resolve_gauge(site_id)
        cache = os.path.join(DATA_DIR, f"usgs-{site_id}")
        terrain = Terrain.load(os.path.join(cache, "terrain.npz"))
        with open(os.path.join(cache, "roads-2017-08-24.json")) as f:
            road_counts = json.load(f)
        with SessionLocal() as db:
            zones = list(db.scalars(select(Zone).where(Zone.region == site.region).order_by(Zone.name)))
            zone_geoms = gpd.GeoSeries([to_shape(z.boundary) for z in zones], crs=4326).to_crs(terrain.crs_epsg)
            times15 = timesteps(START, END, timedelta(minutes=15))
            rating = fit_event_rating(db, site_id)
            stage = observed_stage(db, site_id, times15, rating)
            depth, depth_method = depth_over_channel(site, stage, terrain)
            fim, refused = load_fim_library(site, terrain.crs_epsg)
            river = build_river_driver(site, terrain, stage, depth, fim, refused)
            segments = basin_segments(db, site, terrain.crs_epsg, road_counts["edge_ids"])
            net = engine.build_network(segments, terrain, np.array([], dtype=np.int64), river.threshold, river.known)
        bounds = engine.zone_boundaries(zones, zone_geoms, net)
        _, evaluated = engine.evaluated_zones(net, bounds)
        unknown_blocked = stage.stage_ft >= site.thresholds.minor_ft
        idx = [i for i, t in enumerate(times15) if (t - START) % STEP == timedelta(0)]
        times = [times15[i] for i in idx]
        log.info("%s: network built in %.0f s: %d roads, %d zones, %d ticks", site_id, time.time() - t0, len(net.u), len(zones), len(times))

        # candidate depots: OSM fire stations inside this basin's roads, snapped to a modelled road
        minx, miny, maxx, maxy = net.geometry.total_bounds
        box = gpd.GeoSeries([Point(minx, miny), Point(maxx, maxy)], crs=terrain.crs_epsg).to_crs(4326)
        bbox = (box.iloc[0].x, box.iloc[0].y, box.iloc[1].x, box.iloc[1].y)
        tracked = json.load(open(CANDIDATES)) if os.path.exists(CANDIDATES) else {"sites": {}}
        if not args.refetch and site_id in tracked["sites"]:
            entry = tracked["sites"][site_id]
            found, fetched_at = entry["depots"], entry["osm_fetched_at"]
            log.info("%s: using the %d tracked candidate depots (OSM fetch %s)", site_id, len(found), fetched_at)
        else:
            found, fetched_at = fire_stations(bbox, os.path.join(cache, "depot_candidates.json"))
        cands = []
        for d in found:
            xy = gpd.GeoSeries([Point(d["lon"], d["lat"])], crs=4326).to_crs(terrain.crs_epsg).iloc[0]
            edge, dist = depot_reach.snap_to_road(net, xy.x, xy.y)
            if dist <= depot_reach.MAX_SNAP_M:
                cands.append({**d, "edge": edge, "snap_m": round(dist, 1), "x": xy.x})
        # A depot is a valid origin only if, at base flow (the first step), it reaches the evaluated zones: a station that
        # snaps onto a road fragment cut off from the network even when dry (not connected at base flow) is dropped.
        i0 = idx[0]
        valid = []
        for d in cands:
            s0, _ = depot_reach.zone_states(net, bounds, evaluated, float(river.level[i0]), bool(unknown_blocked[i0]), d["edge"])
            if evaluated.any() and (s0[evaluated] == depot_reach.REACHABLE).mean() >= 0.9:
                valid.append(d)
        valid.sort(key=lambda d: d["x"])  # spread west to east: first, middle, last
        picks = [valid[i] for i in sorted({0, len(valid) // 2, len(valid) - 1})][:PER_GAUGE] if valid else []
        log.info("%s: %d fire stations in the box, %d within %.0f m of a modelled road, %d connected to the network at base flow; using %d",
                 site_id, len(found), len(cands), depot_reach.MAX_SNAP_M, len(valid), len(picks))

        states = np.zeros((len(picks), len(times), len(zones)), dtype=np.uint8)
        depot_road_dry = np.zeros((len(picks), len(times)), dtype=bool)
        for k, d in enumerate(picks):
            for ti, i in enumerate(idx):
                states[k, ti], depot_road_dry[k, ti] = depot_reach.zone_states(
                    net, bounds, evaluated, float(river.level[i]), bool(unknown_blocked[i]), d["edge"])
        # Self-check against the engine: wherever a depot is in the main network, "not reachable" from it must be exactly
        # the zones the engine calls isolated (optimistic run) at that step. The new code must reduce to the old.
        checked = mismatched = 0
        for k, d in enumerate(picks):
            for ti, i in enumerate(idx):
                if not depot_reach.in_main_network(net, float(river.level[i]), d["edge"]):
                    continue
                isolated = engine.isolation_step(net, bounds, evaluated, float(river.level[i]), None, unknown_blocked=False).isolated
                checked += 1
                if not np.array_equal(isolated, (states[k, ti] == depot_reach.NOT_REACHABLE) & evaluated):
                    mismatched += 1
        log.info("%s: engine agreement: %d depot-ticks checked, %d mismatched", site_id, checked, mismatched)
        if mismatched:
            raise SystemExit(f"{site_id}: depot reach disagrees with the isolation engine at {mismatched} of {checked} depot-ticks")
        meta = {"site": site_id, "name": site.name, "region": site.region, "generated_at": datetime.now(timezone.utc).isoformat(),
                "window_utc": [str(START), str(END)], "step_minutes": 30, "osm_fetched_at": fetched_at, "overpass": OVERPASS,
                "zone_ids": [str(z.id) for z in zones], "times": [t.isoformat() for t in times],
                "depots": [{k2: d[k2] for k2 in ("osm", "name", "lat", "lon", "snap_m")} for d in picks],
                "states": {str(v): name for v, name in depot_reach.STATE_NAMES.items()},
                "engine_agreement": {"depot_ticks_checked": checked, "mismatched": mismatched}}
        np.savez_compressed(os.path.join(cache, "depot_access.npz"), states=states, depot_road_dry=depot_road_dry,
                            meta=np.array(json.dumps(meta)))
        summary[site_id] = {"depots": [d["name"] for d in picks], "seconds": round(time.time() - t0)}
        print(json.dumps({site_id: summary[site_id]}), flush=True)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
