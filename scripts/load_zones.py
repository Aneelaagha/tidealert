"""Create zones for the White Oak Bayou FIM reach: one per 2020 census block group.

A block group becomes a zone if it intersects the largest inundation extent in
the NWS FIM library for HGTT2 (45.7 ft stage), i.e. it has some area the
library actually models as floodable. Block groups are used because NFIP
claims carry a census block group GEOID, so claims join to zones exactly.

Run scripts/pull_fim_library.py first.

Usage (from the repo root):
    .venv/bin/python scripts/load_zones.py
"""
import os
import sys
from datetime import datetime, timezone

import geopandas as gpd
from shapely.geometry import MultiPolygon

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from geoalchemy2.shape import from_shape  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Zone  # noqa: E402
from app.services.census import fetch_block_groups  # noqa: E402

FIM_PATH = os.path.join(os.path.dirname(__file__), "..", "backend", "app", "data", "fim_hgtt2", "fim_extents.gpkg")
REGION = "White Oak Bayou (NWS FIM HGTT2 reach)"


def main() -> None:
    extents = gpd.read_file(FIM_PATH, layer="inundation_extents")
    max_extent = extents.loc[extents["stage_ft"].idxmax(), "geometry"]
    block_groups = fetch_block_groups(2020, max_extent.bounds)
    block_groups = block_groups[block_groups.intersects(max_extent)]
    print(f"{len(block_groups)} 2020 block groups intersect the {extents['stage_ft'].max()} ft FIM extent")

    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        for _, bg in block_groups.iterrows():
            boundary = bg.geometry
            if isinstance(boundary, MultiPolygon):
                # zones.boundary is a POLYGON; keep the main part.
                print(f"  {bg.GEOID}: multipolygon with {len(boundary.geoms)} parts, keeping the largest")
                boundary = max(boundary.geoms, key=lambda g: g.area)

            zone = db.scalar(select(Zone).where(Zone.census_geoid == bg.GEOID))
            if zone is None:
                zone = Zone(census_geoid=bg.GEOID, last_updated_at=now)
                db.add(zone)
            zone.name = f"Block group {bg.GEOID}"
            zone.region = REGION
            zone.boundary = from_shape(boundary, srid=4326)
            zone.population_count = int(bg.POP100)
            zone.last_updated_at = now
        db.commit()

    print(f"Loaded {len(block_groups)} zones, total 2020 population {int(block_groups.POP100.sum()):,}")


if __name__ == "__main__":
    main()
