"""Dry run of the isolation pipeline's DATA stages for one gauge: what a full run would cost, before running it.

Runs, with timing and peak memory, exactly the input stages of scripts/run_isolation_pipeline.py: gauge ingest,
3DEP DEM download, terrain (flow directions, HAND inputs), OSM roads, and street-block zones. Stops before the river
driver, the isolation engine and the backtest: it produces no flood, isolation or lead-time result. Caches land in
backend/app/data/usgs-<site>/ like a real run, so a later full run reuses them.

The gauge record is ingested but not read back or summarised here (only the row count is reported).

Usage (from the repo root):
    .venv/bin/python scripts/helene_dry_run.py 03451500 --out report.json
"""
import argparse
import json
import logging
import os
import resource
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import geopandas as gpd  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Zone  # noqa: E402
from app.services.gauge_site import resolve_gauge  # noqa: E402
from app.services.ingest import ingest_gauge, ingest_roads  # noqa: E402
from app.services.street_blocks import generate_zones  # noqa: E402
from app.services.terrain import Terrain, build_terrain, download_dem, utm_epsg  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "backend", "app", "data")
START = datetime(2024, 9, 25, 4, tzinfo=timezone.utc)  # 2024-09-25 00:00 EDT
END = datetime(2024, 10, 1, 4, tzinfo=timezone.utc)  # 2024-10-01 00:00 EDT


def peak_rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6  # bytes on macOS


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("site")
    p.add_argument("--out")
    args = p.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    report = {"site": args.site, "window_utc": [str(START), str(END)], "stages": {}}

    def stage(name, fn):
        t0 = time.time()
        value = fn()
        report["stages"][name] = {"seconds": round(time.time() - t0, 1), "peak_rss_mb_so_far": round(peak_rss_mb())}
        print(f"  {name}: {report['stages'][name]['seconds']} s", flush=True)
        return value

    site = stage("resolve gauge", lambda: resolve_gauge(args.site))
    report.update({"name": site.name, "region": site.region, "nws_lid": site.nws_lid,
                   "flood_map_library": bool(site.fim_mapserver_url)})
    epsg = utm_epsg(site.point.x, site.point.y)
    km2 = lambda g: round(gpd.GeoSeries([g], crs=4326).to_crs(epsg).iloc[0].area / 1e6, 1)  # noqa: E731
    report["study_area"] = {"modelled_km2": km2(site.basin),
                            "full_basin_km2": km2(site.full_basin) if site.full_basin is not None else km2(site.basin),
                            "note": site.study_area_note or "whole basin"}
    cache = os.path.join(DATA_DIR, f"usgs-{site.site_id}")
    os.makedirs(cache, exist_ok=True)
    osm_date = (START - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")

    with SessionLocal() as db:
        counts = stage("gauge ingest", lambda: ingest_gauge(db, site, START, END))
        report["gauge_rows_ingested"] = counts  # counts only: the record itself is not read back here

        dem_path = os.path.join(cache, "dem_3dep.tif")
        if not os.path.exists(dem_path):
            stage("DEM download (3DEP)", lambda: download_dem(site, dem_path))
        terrain_path = os.path.join(cache, "terrain.npz")
        if os.path.exists(terrain_path):
            terrain = stage("terrain load (cached)", lambda: Terrain.load(terrain_path))
        else:
            terrain = stage("terrain build", lambda: build_terrain(site, dem_path))
            terrain.save(terrain_path)
        report["dem"] = {"cells": [int(x) for x in terrain.dem.shape], "cell_m": round(abs(terrain.transform.a), 2),
                         "mainstem_cells": int(terrain.mainstem.sum()), "in_basin_cells": int(terrain.in_basin.sum()),
                         "file_mb": round(os.path.getsize(dem_path) / 1e6, 1), "crs_epsg": terrain.crs_epsg}

        roads_path = os.path.join(cache, f"roads-{osm_date[:10]}.json")
        if not os.path.exists(roads_path):
            loaded = stage("OSM roads (Overpass)", lambda: ingest_roads(db, site, osm_date))
            with open(roads_path + ".tmp", "w") as f:
                json.dump(loaded, f)
            os.replace(roads_path + ".tmp", roads_path)
        with open(roads_path) as f:
            road_counts = json.load(f)
        report["roads"] = {k: v for k, v in road_counts.items() if k != "edge_ids"}

        stage("street-block zones", lambda: generate_zones(db, site, terrain.crs_epsg, road_counts["edge_ids"]))
        n, pop = db.execute(select(func.count(), func.coalesce(func.sum(Zone.population_count), 0))
                            .where(Zone.region == site.region)).one()
        report["zones"] = {"street_blocks": n, "population": int(pop)}

    report["peak_rss_mb"] = round(peak_rss_mb())
    text = json.dumps(report, indent=1, default=str)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text)
    print(text)


if __name__ == "__main__":
    main()
