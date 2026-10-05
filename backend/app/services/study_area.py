"""Study-area clips: a registered gauge models only part of its upstream basin.

By default a gauge's study area is its whole upstream drainage basin (NLDI). Some basins are too large to model in
one pass (the French Broad at Asheville is 2,446 km^2; its full-basin 3DEP export fails), so a clip limits the study
area to a documented, citable boundary. Everything downstream (DEM, HAND, roads, street blocks) reads the clipped
basin, and the site keeps the full basin so the coverage cut can always be stated.

A clip can also exclude the basins of other gauges in the same run: the Swannanoa (03451000) drains into the French
Broad above the Asheville gauge, and excluding it keeps the two regions' street blocks disjoint (no zone modelled
twice).

The clipped polygon is cached with where it came from (backend/app/data/usgs-<site>/study_area.json), so a rerun
models exactly the same area.
"""
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

import requests
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
TIGER_PLACES = ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_Census2020/MapServer/26/"
                "query")


@dataclass(frozen=True)
class Clip:
    label: str  # short, for the region name
    place_geoid: str  # Census 2020 incorporated place to intersect with
    place_name: str
    exclude_basins_of: tuple[str, ...] = ()  # other gauges whose upstream basins are removed
    reason: str = ""


CLIPS = {
    "03451500": Clip(
        label="clipped to Asheville city limits",
        place_geoid="3702140", place_name="Asheville city, NC (Census 2020)",
        exclude_basins_of=("03451000",),
        reason=("the full 2,446 km^2 basin can't be exported from 3DEP in one request, and the event is being tested "
                "for HAND behaviour near the gauged reach, not full-basin coverage"),
    ),
}


@dataclass(frozen=True)
class StudyArea:
    clip: Clip
    full_basin: BaseGeometry
    note: str  # plain statement of the cut, for reports and the run's caveats


def _place(geoid: str) -> BaseGeometry:
    r = requests.get(TIGER_PLACES, params={"where": f"GEOID='{geoid}'", "outFields": "NAME,GEOID",
                                           "returnGeometry": "true", "outSR": "4326", "f": "geojson"}, timeout=120)
    r.raise_for_status()
    features = r.json()["features"]
    if len(features) != 1:
        raise RuntimeError(f"Census place {geoid}: expected one boundary, got {len(features)}")
    return shape(features[0]["geometry"])


def apply(site_id: str, basin: BaseGeometry, basin_of: Callable[[str], BaseGeometry],
          place: Callable[[str], BaseGeometry] = _place, cache_dir: Optional[str] = None) -> tuple[BaseGeometry, Optional[StudyArea]]:
    """The study area for a gauge: its basin, or the registered clip of it. `basin_of` gives another gauge's basin."""
    clip = CLIPS.get(site_id)
    if clip is None:
        return basin, None
    cache = os.path.join(cache_dir or os.path.join(DATA_DIR, f"usgs-{site_id}"), "study_area.json")
    if os.path.exists(cache):
        with open(cache) as f:
            cached = json.load(f)
        clipped = shape(cached["geometry"])
    else:
        clipped = basin.intersection(place(clip.place_geoid))
        for other in clip.exclude_basins_of:
            clipped = clipped.difference(basin_of(other))
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with open(cache + ".tmp", "w") as f:
            json.dump({"site": site_id, "geometry": mapping(clipped), "place_geoid": clip.place_geoid,
                       "excluded_basins_of": list(clip.exclude_basins_of),
                       "fetched_at": datetime.now(timezone.utc).isoformat()}, f)
        os.replace(cache + ".tmp", cache)
    if clipped.is_empty:
        raise RuntimeError(f"USGS {site_id}: the study-area clip is empty")
    excluded = f", excluding the basins of USGS {', '.join(clip.exclude_basins_of)}" if clip.exclude_basins_of else ""
    note = (f"Study area clipped to {clip.place_name}{excluded}: only street blocks inside it are modelled, because "
            f"{clip.reason}.")
    return clipped, StudyArea(clip=clip, full_basin=basin, note=note)
