"""Direct-rainfall flooding driver, independent of river stage.

Rainfall: AORC hourly precipitation (the forcing of NWM v2.1 retrospective,
1 km, gauge-corrected radar analysis), read anonymously from
s3://noaa-nwm-retrospective-2-1-zarr-pds/precip.zarr. GPM IMERG would be the
drop-in alternative but needs NASA Earthdata credentials. The AORC value at
hour t is taken as the mean rate over the hour ending at t.

Ponding model, per NHD catchment c (cells whose nearest drainage is reach c):

    drainage capacity C = NOAA Atlas 14 2-year, 60-minute rainfall depth at
                          the basin centroid, expressed as a rate. Urban storm
                          sewers are typically designed for the 2-year storm
                          (e.g. City of Houston Infrastructure Design Manual).
    excess storage   S_c(t) = max(0, S_c(t - dt) + (P_c(t) - C) * dt)
    ponded volume    V_c(t) = S_c(t) * A_c
    water level      h_c(t) = the level above c's drainage at which the
                          terrain below it (cells with HAND <= h) holds V_c.

So excess rain fills each catchment's lowest ground first, in order of HAND
relative to the full drainage network. All excess becomes surface water
(saturated, largely impervious ground).

Coupling to the river (a stated modeling assumption, not a measurement):
storm drains discharge into the gauged bayou and its tributaries, so while
the gauge is at or above its minor (flood) stage the outfalls are partly
submerged and drains keep only RESIDUAL_DRAIN_FRACTION of C. Below flood
stage, C is the full Atlas 14 rate. The threshold is the site's minor flood
stage (NWS, or its logged percentile fallback); tributary outfalls are
assumed to back up with the mainstem.

RESIDUAL_DRAIN_FRACTION = 0.5 was chosen on Greens Bayou (USGS 08076000)
only, bracketed by 0.25 and 1.0 in every report. Zero (the first version)
isolated every evaluated Greens zone: Harvey's ~0.9 m of rain fills most
shallow depressions by itself, so with no drainage at all nothing ever
empties.
"""
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pyproj
import requests
import s3fs
import xarray as xr

from app.services.gauge_site import GaugeSite
from app.services.terrain import Terrain

log = logging.getLogger(__name__)

AORC_ZARR = "noaa-nwm-retrospective-2-1-zarr-pds/precip.zarr"
ATLAS14_URL = "https://hdsc.nws.noaa.gov/cgi-bin/new/cgi_readH5.py"
# Atlas 14 PFDS rows are durations (5, 10, 15, 30, 60 min, 2 h, ...); columns
# are average recurrence intervals (1, 2, 5, 10, 25, 50, 100, 200, 500, 1000 yr).
ATLAS14_ROW_60MIN = 4
ATLAS14_COL_2YR = 1
MM_PER_INCH = 25.4
# Share of drain capacity kept while the receiving bayou is at/above flood stage (fit on Greens Bayou).
RESIDUAL_DRAIN_FRACTION = 0.5
RESIDUAL_DRAIN_BRACKET = (0.25, 1.0)


@dataclass
class RainfallSeries:
    times: list[datetime]  # hour ending
    catchments: np.ndarray  # COMIDs
    rate_mm_hr: np.ndarray  # (time, catchment)
    basin_mean_mm_hr: np.ndarray  # (time,)


@dataclass
class PondingLevels:
    times: list[datetime]
    catchments: np.ndarray
    level_m: np.ndarray  # (time, catchment); -inf where nothing is ponded
    capacity_mm_hr: float
    drains_blocked: np.ndarray  # (time,) bool


def drainage_capacity_mm_hr(site: GaugeSite) -> float:
    """NOAA Atlas 14 2-year 60-minute rainfall depth at the basin centroid, as mm/hr."""
    centroid = site.basin.centroid
    resp = requests.get(
        ATLAS14_URL,
        params={"lat": round(centroid.y, 4), "lon": round(centroid.x, 4), "type": "pf", "data": "depth",
                "units": "english", "series": "pds"},
        timeout=120,
    )
    resp.raise_for_status()
    match = re.search(r"quantiles = (\[\[.*?\]\]);", resp.text, re.S)
    if not match:
        raise RuntimeError(f"Unexpected Atlas 14 response: {resp.text[:200]!r}")
    table = json.loads(match.group(1).replace("'", '"'))  # nested list of numeric strings
    return float(table[ATLAS14_ROW_60MIN][ATLAS14_COL_2YR]) * MM_PER_INCH


def aorc_rainfall(terrain: Terrain, start: datetime, end: datetime) -> RainfallSeries:
    ds = xr.open_zarr(s3fs.S3Map(AORC_ZARR, s3=s3fs.S3FileSystem(anon=True)), consolidated=True)
    lcc = pyproj.CRS.from_proj4(ds.RAINRATE.attrs["proj4"])
    to_lcc = pyproj.Transformer.from_crs(terrain.crs_epsg, lcc, always_xy=True)

    rows, cols = np.nonzero(terrain.in_basin & (terrain.catchment_comid > 0))
    xs = terrain.transform.c + (cols + 0.5) * terrain.transform.a
    ys = terrain.transform.f + (rows + 0.5) * terrain.transform.e
    lx, ly = to_lcc.transform(xs, ys)
    x0, dx = float(ds.x[0]), float(ds.x[1] - ds.x[0])
    y0, dy = float(ds.y[0]), float(ds.y[1] - ds.y[0])
    ix = np.rint((lx - x0) / dx).astype(int)
    iy = np.rint((ly - y0) / dy).astype(int)
    ix0, ix1, iy0, iy1 = ix.min(), ix.max() + 1, iy.min(), iy.max() + 1

    rate = (
        ds.RAINRATE.isel(x=slice(ix0, ix1), y=slice(iy0, iy1))
        .sel(time=slice(start.replace(tzinfo=None), end.replace(tzinfo=None)))
        .load()
    )
    rate_mm_hr = rate.values * 3600.0  # mm/s mean over the hour -> mm/hr
    times = [datetime.fromisoformat(str(t)[:19] + "+00:00") for t in rate.time.values]

    # Area-weight each AORC cell's rain into catchments by DEM-cell counts.
    comids = terrain.catchment_comid[rows, cols]
    catchments, catch_idx = np.unique(comids, return_inverse=True)
    aorc_flat = (iy - iy0) * (ix1 - ix0) + (ix - ix0)
    per_cell = rate_mm_hr.reshape(len(times), -1)[:, aorc_flat]  # (time, dem cells)
    counts = np.bincount(catch_idx, minlength=len(catchments))
    by_catchment = np.stack([np.bincount(catch_idx, weights=row, minlength=len(catchments)) for row in per_cell])
    by_catchment /= counts
    return RainfallSeries(
        times=times,
        catchments=catchments,
        rate_mm_hr=by_catchment,
        basin_mean_mm_hr=per_cell.mean(axis=1),
    )


def ponding_levels(
    terrain: Terrain,
    rain: RainfallSeries,
    times: list[datetime],
    capacity_mm_hr: float,
    drains_blocked: np.ndarray,
    residual_fraction: float = RESIDUAL_DRAIN_FRACTION,
) -> PondingLevels:
    """Water level above drainage (m) per catchment at each engine timestep.
    drains_blocked[i]: the receiving bayou is at/above flood stage at step i, so drains keep only
    residual_fraction of their capacity."""
    hour_ts = np.array([t.timestamp() for t in rain.times])
    step_ts = np.array([t.timestamp() for t in times])
    dt_hr = np.diff(step_ts, prepend=step_ts[0] - (step_ts[1] - step_ts[0])) / 3600.0
    # Rate at a step = the AORC hour containing it (hour ending at or after the step).
    hour_idx = np.clip(np.searchsorted(hour_ts, step_ts, side="left"), 0, len(hour_ts) - 1)
    rate = rain.rate_mm_hr[hour_idx]  # (step, catchment)

    storage_mm = np.zeros(len(rain.catchments))
    level = np.full((len(times), len(rain.catchments)), -np.inf)
    area = terrain.cell_area_m2
    hand = terrain.hand_network
    in_catchment = terrain.in_basin & np.isfinite(hand)

    # Storage-level curve per catchment from its sorted HAND values.
    curves = []
    for comid in rain.catchments:
        h = np.sort(hand[in_catchment & (terrain.catchment_comid == comid)])
        k = np.arange(1, len(h) + 1)
        stored_at = (k * h - np.cumsum(h)) * area  # m3 held below level h[k-1]
        curves.append((h, stored_at, len(h) * area))

    for i in range(len(times)):
        capacity = capacity_mm_hr * (residual_fraction if drains_blocked[i] else 1.0)
        storage_mm = np.maximum(0.0, storage_mm + (rate[i] - capacity) * dt_hr[i])
        for j, (h, stored_at, catchment_area) in enumerate(curves):
            volume = storage_mm[j] / 1000.0 * catchment_area
            if volume <= 0 or len(h) == 0:
                continue
            k = int(np.searchsorted(stored_at, volume, side="right"))  # cells below the level
            level[i, j] = h[k - 1] + (volume - stored_at[k - 1]) / (k * area)
    return PondingLevels(times=times, catchments=rain.catchments, level_m=level, capacity_mm_hr=capacity_mm_hr,
                         drains_blocked=np.asarray(drains_blocked, dtype=bool))
