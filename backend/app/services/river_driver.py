"""The river driver: where the river floods, from an NWS flood-map library or (lower confidence) HAND.

Shared by the isolation pipeline (scripts/run_isolation_pipeline.py) and the
case matcher. See docs/algorithms/isolation-engine.md.
"""
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import geopandas as gpd
import numpy as np
from rasterio.features import rasterize
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Zone
from app.services import isolation_engine as engine
from app.services.fim_library import fetch_fim_extents
from app.services.gauge_site import FEET_TO_METERS, GaugeSite, resolve_gauge
from app.services.stage import StageSeries, fit_event_rating, observed_stage, timesteps
from app.services.street_blocks import basin_segments
from app.services.terrain import Terrain

log = logging.getLogger(__name__)
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
# Hurricane Harvey event window (US Central), the default replay.
HARVEY_START = datetime(2017, 8, 25, 5, tzinfo=timezone.utc)  # 2017-08-25 00:00 CDT
HARVEY_END = datetime(2017, 9, 3, 5, tzinfo=timezone.utc)  # 2017-09-03 00:00 CDT
STEP = timedelta(minutes=15)

# Standard-time abbreviations (NWPS, USGS) -> IANA zones that observe daylight saving; zones that
# do not observe it use a fixed offset instead.
DST_ZONES = {"EST": "America/New_York", "CST": "America/Chicago", "MST": "America/Denver",
             "PST": "America/Los_Angeles", "AKST": "America/Anchorage", "HST": "Pacific/Honolulu"}
STANDARD_OFFSETS_H = {"EST": -5, "CST": -6, "MST": -7, "PST": -8, "AKST": -9, "HST": -10}


def local_zone(site: GaugeSite):
    """The gauge's local time zone: NWS NWPS first, then the USGS site record, UTC only if neither has one."""
    if site.nws_time_zone:
        try:
            return ZoneInfo(DST_ZONES.get(site.nws_time_zone, site.nws_time_zone))
        except Exception:
            log.warning("USGS %s: NWS time zone %r not recognised", site.site_id, site.nws_time_zone)
    abbr = site.usgs_time_zone
    if abbr in DST_ZONES and site.usgs_uses_dst is not False:
        return ZoneInfo(DST_ZONES[abbr])
    if abbr in STANDARD_OFFSETS_H:
        return timezone(timedelta(hours=STANDARD_OFFSETS_H[abbr]), abbr)
    log.warning("USGS %s: no time zone from NWS (%r) or USGS (%r); FALLBACK to UTC for claim dates",
                site.site_id, site.nws_time_zone, abbr)
    return timezone.utc


def depth_over_channel(site: GaugeSite, stage: StageSeries, terrain: Terrain) -> tuple[np.ndarray, str]:
    """Water depth (m) over the snapped DEM channel at the gauge, per timestep."""
    wse = site.stage_to_wse_m(stage.stage_ft)
    if wse is not None:
        return wse - terrain.gauge_channel_elev_m, (
            f"stage + gauge datum ({site.gauge_datum_altitude_ft} ft NAVD88) - DEM channel "
            f"elevation at gauge ({terrain.gauge_channel_elev_m:.2f} m)")
    base = float(stage.stage_ft.min())
    log.warning("USGS %s: gauge datum is %s, not NAVD88; FALLBACK depth = stage above the event's lowest "
                "stage (%.2f ft)", site.site_id, site.gauge_vertical_datum, base)
    return (stage.stage_ft - base) * FEET_TO_METERS, f"FALLBACK: stage above event minimum {base:.2f} ft"


@dataclass
class RiverDriver:
    """River-driver rasters and level series, in the driver's own units (see isolation_engine)."""
    method: str
    confidence: str  # "primary" | "LOWER CONFIDENCE"
    caveat: Optional[str]  # recorded on evaluated zones when confidence is lower
    threshold: np.ndarray  # river level at which each cell floods; inf = never within range
    known: np.ndarray  # bool: the source covers the river here
    level: np.ndarray  # river level per timestep
    units: str
    coverage_desc: str


def gauge_nhd_reach(site: GaugeSite, terrain: Terrain) -> np.ndarray:
    """Mainstem cells of the gauge's own NHDPlus reach (its COMID, between confluences)."""
    mask = terrain.mainstem & (terrain.network_comid == site.comid)
    if not mask.any():
        raise RuntimeError(f"USGS {site.site_id}: gauge COMID {site.comid} has no mainstem cells in the basin")
    return mask


def fim_first_stage(terrain: Terrain, fim: gpd.GeoDataFrame) -> np.ndarray:
    """Lowest library stage whose mapped extent covers each cell (inf where none does)."""
    first = np.full(terrain.dem.shape, np.inf)
    for stage_ft, geom in sorted(zip(fim.stage_ft, fim.geometry), reverse=True):
        wet = rasterize([(geom, 1)], out_shape=terrain.dem.shape, transform=terrain.transform, fill=0).astype(bool)
        first[wet] = stage_ft
    return first


def build_river_driver(site: GaugeSite, terrain: Terrain, stage: StageSeries, depth: np.ndarray,
                       fim: Optional[gpd.GeoDataFrame]) -> RiverDriver:
    if fim is not None:
        stages = np.sort(fim.stage_ft.to_numpy())
        # Coverage is the library's own largest mapped extent (plus one DEM cell for rendering edges):
        # outside it the map makes no statement, whatever the gauge's reach is.
        coverage_geom = fim.geometry.iloc[int(np.argmax(fim.stage_ft))].buffer(abs(terrain.transform.a))
        known = rasterize([(coverage_geom, 1)], out_shape=terrain.dem.shape, transform=terrain.transform,
                          fill=0).astype(bool) & terrain.in_basin
        idx = np.minimum(np.searchsorted(stages, stage.stage_ft, side="left"), len(stages) - 1)
        level = np.where(stage.stage_ft < stages[0], -np.inf, stages[idx])
        n_above = int((stage.stage_ft > stages[-1]).sum())
        if n_above:
            log.warning("USGS %s: stage exceeds the NWS library's highest stage (%.1f ft) for %d steps; the "
                        "highest mapped extent is used", site.site_id, stages[-1], n_above)
        return RiverDriver(
            method=f"NWS flood map library ({site.nws_lid}, {len(stages)} stages {stages[0]}-{stages[-1]} ft)",
            confidence="primary", caveat=None, threshold=fim_first_stage(terrain, fim), known=known,
            level=level, units="ft (library stage)",
            coverage_desc=f"NWS map's largest mapped extent ({known.sum() * terrain.cell_area_m2 / 1e6:.2f} km2 "
                          f"in basin); everything else draining to the mainstem is unknown")
    reach = gauge_nhd_reach(site, terrain)
    drain = terrain.mainstem_drain
    known = (drain >= 0) & reach.ravel()[np.maximum(drain, 0)].reshape(drain.shape)
    caveat = (f"River flooding from HAND (height above nearest drainage, snapped channel) because NWS publishes no "
              f"flood-map library for USGS {site.site_id}; assumes constant depth along the reach. Lower confidence.")
    log.warning("USGS %s: %s", site.site_id, caveat)
    return RiverDriver(
        method="HAND (snapped channel), constant depth along the gauge's NHD reach",
        confidence="LOWER CONFIDENCE", caveat=caveat,
        threshold=np.where(np.isnan(terrain.hand_mainstem), np.inf, terrain.hand_mainstem), known=known,
        level=depth, units="m (depth over channel)",
        coverage_desc=f"cells draining to the gauge's own NHDPlus reach, COMID {site.comid}")


def river_flood_mask(terrain: Terrain, river: RiverDriver, i: int) -> np.ndarray:
    """Cells the river driver floods at step i (same rule as isolation_engine); unknown cells are dry."""
    return river.known & (river.threshold <= river.level[i]) & terrain.in_basin


@dataclass
class SiteContext:
    """Everything the isolation engine needs for one gauge and event window, from caches and the database."""
    site: GaugeSite
    tz: object
    terrain: Terrain
    times: list[datetime]
    stage: StageSeries
    depth: np.ndarray
    river: RiverDriver
    fim: Optional[gpd.GeoDataFrame]
    segments: gpd.GeoDataFrame
    zones: list[Zone]
    zone_geoms: gpd.GeoSeries
    net: "engine.RoadNetwork"
    bounds: "engine.ZoneBoundaries"
    evaluated: np.ndarray
    unknown_blocked: np.ndarray


def load_site_context(db: Session, site_id: str, start: datetime = HARVEY_START, end: datetime = HARVEY_END,
                      step: timedelta = STEP) -> SiteContext:
    """Rebuild a gauge's engine inputs from the pipeline's caches and the database (no ingestion).

    Run scripts/run_isolation_pipeline.py for the gauge first: it downloads and stores what this loads.
    """
    from geoalchemy2.shape import to_shape

    site = resolve_gauge(site_id)
    tz = local_zone(site)
    cache = os.path.join(DATA_DIR, f"usgs-{site.site_id}")
    osm_date = (start - timedelta(days=1)).strftime("%Y-%m-%d")
    roads_path = os.path.join(cache, f"roads-{osm_date}.json")
    terrain_path = os.path.join(cache, "terrain.npz")
    for path in (roads_path, terrain_path):
        if not os.path.exists(path):
            raise FileNotFoundError(f"{path} missing: run scripts/run_isolation_pipeline.py {site.site_id} first")
    terrain = Terrain.load(terrain_path)
    with open(roads_path) as f:
        edge_ids = json.load(f)["edge_ids"]

    times = timesteps(start, end, step)
    stage = observed_stage(db, site.site_id, times, fit_event_rating(db, site.site_id))
    depth, _ = depth_over_channel(site, stage, terrain)
    fim = fetch_fim_extents(site.fim_mapserver_url).to_crs(terrain.crs_epsg) if site.fim_mapserver_url else None
    river = build_river_driver(site, terrain, stage, depth, fim)
    segments = basin_segments(db, site, terrain.crs_epsg, edge_ids)
    zones = list(db.scalars(select(Zone).where(Zone.region == site.region).order_by(Zone.name)))
    zone_geoms = gpd.GeoSeries([to_shape(z.boundary) for z in zones], crs=4326).to_crs(terrain.crs_epsg)
    net = engine.build_network(segments, terrain, np.array([], dtype=np.int64), river.threshold, river.known)
    bounds = engine.zone_boundaries(zones, zone_geoms, net)
    _, evaluated = engine.evaluated_zones(net, bounds)
    return SiteContext(
        site=site, tz=tz, terrain=terrain, times=times, stage=stage, depth=depth, river=river, fim=fim,
        segments=segments, zones=zones, zone_geoms=zone_geoms, net=net, bounds=bounds, evaluated=evaluated,
        unknown_blocked=stage.stage_ft >= site.thresholds.minor_ft,
    )
