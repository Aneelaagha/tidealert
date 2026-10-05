"""Terrain model for a gauge's basin: DEM, NHD drainage network, and HAND rasters.

Everything is derived from the GaugeSite:

- DEM: USGS 3DEP (meters NAVD88) over the basin's bounding box plus a buffer,
  in the basin's UTM zone, at DEM_TARGET_RES_M (coarser only if the basin is
  too large for one 3DEP export).
- Drainage network: NHDPlus flowlines upstream of the gauge from NLDI
  navigation. "Mainstem" (UM) is the gauged river itself; "network" (UT) is
  the mainstem plus every upstream tributary.
- Flow directions: D8 on the DEM after stream burning (flowline cells lowered
  by STREAM_BURN_M so flow follows the mapped channels), pit filling,
  depression filling and flat resolution (pysheds).
- HAND (height above nearest drainage) relative to the full network, twice:
  * hand_mainstem, for the gauge-stage (overbank/backwater) driver: only
    cells whose nearest drainage is the gauged mainstem (tributary catchments
    are left to the rainfall driver, since the gauge says nothing about
    their water level). It is the highest raw-DEM elevation on the cell's D8
    path to the channel minus the channel elevation: river water reaches a
    cell only once it overtops everything in between, so it is never
    negative. (Taking heights from a separately filled DEM while flow
    directions come from the burned DEM let cells sit below their drainage
    and "flood" at base flow.)
  * hand_network, for the rainfall driver: every cell, on the raw DEM, so
    closed depressions get HAND below their drainage and pond first.
  Both are measured from a snapped channel elevation: the lowest DEM cell
  within CHANNEL_SNAP_RADIUS_M of the drainage cell, because the rasterized
  NHDPlus flowline sits on the bank for about half the mainstem (White Oak:
  47% of mainstem cells more than 1 m above the lowest ground within 30 m).
  The gauge's channel elevation is snapped the same way. HAND still assumes
  constant depth along the channel, so it is only the primary river driver
  for gauges without an NWS flood map.

Each cell's drainage cell is found by following D8 directions with pointer
jumping; cells that leave the grid without reaching a drainage cell get NaN.
"""
import logging
import os
import time
from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import rasterio
import requests
from pysheds.grid import Grid
from rasterio.features import rasterize
from rasterio.transform import Affine
from scipy.ndimage import minimum_filter

from app.services.gauge_site import NLDI, GaugeSite

log = logging.getLogger(__name__)

DEM_URL = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage"
DEM_TARGET_RES_M = 10.0
DEM_MAX_PIXELS = 4000  # per side, per 3DEP export request
DEM_BUFFER_M = 1000.0
DEM_ATTEMPTS = 3  # 3DEP export attempts on transient failure (5xx, connection, timeout)
DEM_BACKOFF_S = 10.0  # waits 10 s, then 30 s
DEM_TILE_PIXELS = 2000  # per side, per request: larger exports fail (the Swannanoa's 2,861 x 2,691 returned HTTP 500
# six times in a row; the French Broad clip's 2,401 x 1,690 succeeded), so larger grids are fetched as tiles
STREAM_BURN_M = 10.0
CHANNEL_SNAP_RADIUS_M = 30.0
# pysheds default D8 codes: N, NE, E, SE, S, SW, W, NW.
DIRMAP = (64, 128, 1, 2, 4, 8, 16, 32)
DIR_OFFSETS = {64: (-1, 0), 128: (-1, 1), 1: (0, 1), 2: (1, 1), 4: (1, 0), 8: (1, -1), 16: (0, -1), 32: (-1, -1)}


@dataclass
class Terrain:
    crs_epsg: int
    transform: Affine
    dem: np.ndarray  # m NAVD88, NaN = nodata
    in_basin: np.ndarray  # bool
    mainstem: np.ndarray  # bool, gauged river cells
    network: np.ndarray  # bool, all NHD flowline cells
    network_comid: np.ndarray  # int, COMID of network cells (0 elsewhere)
    hand_mainstem: np.ndarray  # m, flow-path maximum; NaN outside the mainstem's own catchment
    hand_network: np.ndarray  # m
    mainstem_drain: np.ndarray  # flat index of each cell's mainstem drainage cell, -1 if not mainstem-draining
    catchment_comid: np.ndarray  # COMID of each cell's nearest network drainage (0 if none)
    depression_depth: np.ndarray  # m that depression filling raises each cell (0 outside closed depressions)
    gauge_channel_elev_m: float  # DEM elevation of the mainstem cell nearest the gauge

    @property
    def cell_area_m2(self) -> float:
        return abs(self.transform.a * self.transform.e)

    def save(self, path: str) -> None:
        """Write-then-rename, so an interrupted save never leaves a partial cache file at `path`."""
        tmp = path + ".tmp.npz"
        np.savez_compressed(tmp, crs_epsg=self.crs_epsg, transform=np.array(self.transform)[:6],
                            **{k: getattr(self, k) for k in (
                                "dem", "in_basin", "mainstem", "network", "network_comid", "hand_mainstem",
                                "hand_network", "mainstem_drain", "catchment_comid", "depression_depth",
                                "gauge_channel_elev_m")})
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: str) -> "Terrain":
        data = np.load(path)
        fields = {k: data[k] for k in data.files if k not in ("crs_epsg", "transform")}
        fields["gauge_channel_elev_m"] = float(fields["gauge_channel_elev_m"])
        return cls(crs_epsg=int(data["crs_epsg"]), transform=Affine(*data["transform"]), **fields)


def utm_epsg(lon: float, lat: float) -> int:
    zone = int((lon + 180) // 6) + 1
    return (32600 if lat >= 0 else 32700) + zone


def flowlines(comid: int, mode: str) -> gpd.GeoDataFrame:
    """NHDPlus flowlines navigated upstream from a COMID: mode "UM" (mainstem) or "UT" (with tributaries)."""
    resp = requests.get(
        f"{NLDI}/comid/{comid}/navigation/{mode}/flowlines", params={"distance": 9999, "f": "json"}, timeout=300
    )
    resp.raise_for_status()
    gdf = gpd.GeoDataFrame.from_features(resp.json()["features"], crs=4326)
    gdf["comid"] = gdf["nhdplus_comid"].astype(int)
    return gdf[["comid", "geometry"]]


def _get_with_retry(url: str, params: dict, site_id: str, attempts: int = DEM_ATTEMPTS,
                    sleep=time.sleep) -> requests.Response:
    """The 3DEP service returns intermittent 502/503s (and 500s under load) for requests that succeed minutes later.
    Retry transient failures a bounded number of times with backoff; anything else, or the last failure, raises."""
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.get(url, params=params, timeout=900)
            if resp.status_code < 500:
                resp.raise_for_status()
                return resp
            error: Exception = requests.HTTPError(f"{resp.status_code} from 3DEP", response=resp)
        except (requests.ConnectionError, requests.Timeout) as exc:
            error = exc
        if attempt == attempts:
            raise error
        wait = DEM_BACKOFF_S * 3 ** (attempt - 1)
        log.warning("USGS %s: 3DEP export failed (%s); retry %d of %d in %.0f s", site_id, error, attempt,
                    attempts - 1, wait)
        sleep(wait)
    raise AssertionError("unreachable")


def download_dem(site: GaugeSite, path: str) -> None:
    epsg = utm_epsg(site.point.x, site.point.y)
    basin_utm = gpd.GeoSeries([site.basin], crs=4326).to_crs(epsg).iloc[0]
    xmin, ymin, xmax, ymax = basin_utm.buffer(DEM_BUFFER_M).bounds
    res = max(DEM_TARGET_RES_M, (xmax - xmin) / DEM_MAX_PIXELS, (ymax - ymin) / DEM_MAX_PIXELS)
    if res > DEM_TARGET_RES_M:
        log.warning("USGS %s: basin wider than DEM_MAX_PIXELS cells at 10 m; DEM resolution %.1f m", site.site_id, res)
    width, height = int(np.ceil((xmax - xmin) / res)), int(np.ceil((ymax - ymin) / res))
    ytop = ymin + height * res
    if width <= DEM_TILE_PIXELS and height <= DEM_TILE_PIXELS:
        content = _export(xmin, ymin, width, height, res, epsg, site.site_id)
        with open(path + ".tmp", "wb") as f:
            f.write(content)
    else:
        _download_tiled(xmin, ytop, width, height, res, epsg, site.site_id, path + ".tmp")
    os.replace(path + ".tmp", path)


def _export(xmin: float, ymin: float, width: int, height: int, res: float, epsg: int, site_id: str,
            get=None) -> bytes:
    """One 3DEP export of a width x height grid of res-metre cells whose lower-left corner is (xmin, ymin)."""
    params = {
        "bbox": f"{xmin},{ymin},{xmin + width * res},{ymin + height * res}",
        "bboxSR": epsg,
        "imageSR": epsg,
        "size": f"{width},{height}",
        "format": "tiff",
        "pixelType": "F32",
        "interpolation": "RSP_BilinearInterpolation",
        "f": "image",
    }
    resp = (get or _get_with_retry)(DEM_URL, params, site_id)
    if not resp.content.startswith((b"II*\x00", b"MM\x00*")):
        raise RuntimeError(f"3DEP did not return a GeoTIFF: {resp.content[:200]!r}")
    return resp.content


def _download_tiled(xmin: float, ytop: float, width: int, height: int, res: float, epsg: int, site_id: str,
                    out_path: str, get=None) -> None:
    """Fetch a grid too large for one export as tiles of at most DEM_TILE_PIXELS per side, and stitch them.

    Every tile is cut on the full grid's own cell boundaries, so 3DEP samples exactly the cell centres a single
    export would, and stitching is placing arrays: no resampling, no seam."""
    dem = np.full((height, width), np.nan, dtype=np.float32)
    nodata = None
    tiles = [(r, c) for r in range(0, height, DEM_TILE_PIXELS) for c in range(0, width, DEM_TILE_PIXELS)]
    log.info("USGS %s: DEM %d x %d cells fetched as %d tiles", site_id, width, height, len(tiles))
    for row, col in tiles:
        h, w = min(DEM_TILE_PIXELS, height - row), min(DEM_TILE_PIXELS, width - col)
        x0, y0 = xmin + col * res, ytop - (row + h) * res
        with rasterio.MemoryFile(_export(x0, y0, w, h, res, epsg, site_id, get)) as mem, mem.open() as src:
            if src.shape != (h, w):
                raise RuntimeError(f"3DEP tile at row {row}, col {col}: expected {h} x {w} cells, got {src.shape}")
            dem[row:row + h, col:col + w] = src.read(1)
            nodata = src.nodata if nodata is None else nodata
    profile = dict(driver="GTiff", width=width, height=height, count=1, dtype="float32", crs=f"EPSG:{epsg}",
                   transform=Affine(res, 0, xmin, 0, -res, ytop), nodata=nodata)
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(dem, 1)


def _drainage_index(fdir: np.ndarray, target: np.ndarray, elevation: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """For each cell: flat index of the first target cell downstream (itself if it is one, -1 if none),
    and the highest elevation on the D8 path from the cell to that target, inclusive (NaN cells block)."""
    rows, cols = fdir.shape
    n = rows * cols
    idx = np.arange(n)
    r, c = np.divmod(idx, cols)
    down = np.full(n + 1, n, dtype=np.int64)  # index n is a sink that points to itself
    flat_dir = fdir.ravel()
    for code, (dr, dc) in DIR_OFFSETS.items():
        sel = flat_dir == code
        rr, cc = r[sel] + dr, c[sel] + dc
        ok = (rr >= 0) & (rr < rows) & (cc >= 0) & (cc < cols)
        down[idx[sel][ok]] = rr[ok] * cols + cc[ok]
    is_target = np.append(target.ravel(), False)
    down[np.flatnonzero(is_target)] = np.flatnonzero(is_target)  # drainage cells absorb
    # Pointer jumping: after k rounds each cell points 2^k steps downstream and
    # path_max covers the first 2^k cells of its path.
    path_max = np.append(np.where(np.isnan(elevation.ravel()), np.inf, elevation.ravel()), np.inf)
    while True:
        path_max = np.maximum(path_max, path_max[down])
        nxt = down[down]
        if np.array_equal(nxt, down):
            break
        down = nxt
    drain = down[:n]
    return np.where(is_target[drain], drain, -1), path_max[:n]


def build_terrain(site: GaugeSite, dem_path: str) -> Terrain:
    with rasterio.open(dem_path) as src:
        dem = src.read(1).astype("float64")
        transform, epsg, nodata = src.transform, src.crs.to_epsg(), src.nodata
    if nodata is not None:
        dem[dem == nodata] = np.nan
    dem[dem < -100] = np.nan
    shape = dem.shape

    basin_utm = gpd.GeoSeries([site.basin], crs=4326).to_crs(epsg).iloc[0]
    in_basin = rasterize([(basin_utm, 1)], out_shape=shape, transform=transform, fill=0).astype(bool)

    um = flowlines(site.comid, "UM").to_crs(epsg)
    ut = flowlines(site.comid, "UT").to_crs(epsg)
    # The gauge's own NHD reach continues downstream of the gauge; keep only what is inside the basin.
    um = um.clip(basin_utm.buffer(2 * abs(transform.a)))
    ut = ut.clip(basin_utm.buffer(2 * abs(transform.a)))
    mainstem = rasterize(((g, 1) for g in um.geometry), out_shape=shape, transform=transform,
                         fill=0, all_touched=True).astype(bool)
    network_comid = rasterize(((g, int(c)) for g, c in zip(ut.geometry, ut.comid)), out_shape=shape,
                              transform=transform, fill=0, all_touched=True, dtype="int64")
    network = (network_comid > 0) | mainstem

    # Condition a stream-burned copy of the DEM for flow directions.
    burned = np.where(network, dem - STREAM_BURN_M, dem)
    fill_value = np.nanmax(dem) + 100
    tmp_path = dem_path + ".burned.tif"
    with rasterio.open(dem_path) as src:
        profile = src.profile | {"dtype": "float64", "nodata": -9999.0}
    with rasterio.open(tmp_path, "w", **profile) as dst:
        dst.write(np.where(np.isnan(burned), fill_value, burned), 1)
    grid = Grid.from_raster(tmp_path)
    raster = grid.read_raster(tmp_path)
    conditioned = grid.resolve_flats(grid.fill_depressions(grid.fill_pits(raster)))
    fdir = np.asarray(grid.flowdir(conditioned, dirmap=DIRMAP))
    # Closed-depression depth on the unburned DEM: how much filling raises each cell.
    with rasterio.open(tmp_path, "w", **profile) as dst:
        dst.write(np.where(np.isnan(dem), fill_value, dem), 1)
    raw = grid.read_raster(tmp_path)
    filled = np.asarray(grid.fill_depressions(grid.fill_pits(raw)), dtype="float64")
    depression_depth = np.where(np.isnan(dem), 0.0, filled - np.where(np.isnan(dem), 0.0, dem))
    os.remove(tmp_path)

    drain_net, path_max = _drainage_index(fdir, network, dem)
    safe_drain = np.maximum(drain_net, 0)
    flat_dem = dem.ravel()
    # Channel reference elevation: the rasterized NHD flowline often sits on the bank, so snap each
    # drainage cell to the lowest ground within CHANNEL_SNAP_RADIUS_M (NHDPlus positional error).
    radius_cells = max(1, int(round(CHANNEL_SNAP_RADIUS_M / abs(transform.a))))
    channel_elev = minimum_filter(np.where(np.isnan(dem), np.inf, dem), size=2 * radius_cells + 1).ravel()
    drains_to_mainstem = (drain_net >= 0) & mainstem.ravel()[safe_drain]
    # Stage driver: river water reaches a cell only once it overtops the highest ground
    # on the cell's flow path to the channel, so HAND >= 0 by construction.
    hand_mainstem = np.where(drains_to_mainstem, path_max - channel_elev[safe_drain], np.nan).reshape(shape)
    hand_network = np.where(drain_net >= 0, flat_dem - channel_elev[safe_drain], np.nan).reshape(shape)
    mainstem_drain = np.where(drains_to_mainstem, drain_net, -1).reshape(shape)
    net_comid_flat = network_comid.ravel()
    catchment_comid = np.where(drain_net >= 0, net_comid_flat[safe_drain], 0).reshape(shape)

    # Channel elevation at the gauge: nearest mainstem cell.
    gx, gy = gpd.GeoSeries([site.point], crs=4326).to_crs(epsg).iloc[0].coords[0]
    ms_rows, ms_cols = np.nonzero(mainstem)
    xs, ys = rasterio.transform.xy(transform, ms_rows, ms_cols)
    nearest = int(np.argmin((np.asarray(xs) - gx) ** 2 + (np.asarray(ys) - gy) ** 2))
    gauge_channel_elev = float(channel_elev.reshape(shape)[ms_rows[nearest], ms_cols[nearest]])

    return Terrain(
        crs_epsg=epsg, transform=transform, dem=dem, in_basin=in_basin, mainstem=mainstem, network=network,
        network_comid=network_comid, hand_mainstem=hand_mainstem, hand_network=hand_network,
        mainstem_drain=mainstem_drain, catchment_comid=catchment_comid, depression_depth=depression_depth,
        gauge_channel_elev_m=gauge_channel_elev,
    )
