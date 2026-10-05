"""Read an NWS Flood Inundation Mapping (FIM) library, where NWS publishes one for a gauge.

A FIM library is a set of pre-computed inundation depth grids, one per
water-surface elevation (ft NAVD88, the layer's name; NWS: "inundation areas for
given water surface elevations"), published as raster layers on an ArcGIS
MapServer (URL from the NWPS gauge record). in_gauge_stage converts the layers
to gauge stage: a Houston library reads the same either way (gauge datum 0 ft),
a mountain one does not (the Swannanoa's BLTN7 layers are 1,980-1,996 ft; its
gauge datum is 1,976.37 ft). The bulk-download zips linked from NWPS are not
reliably available, so each stage layer is rendered as a transparent PNG at
PIXEL_M and every painted pixel is treated as wet. Rendering was checked
against the vector flood-category polygons of the HGTT2 library
(IoU 0.95-0.97).
"""
import warnings
from typing import Optional

import geopandas as gpd
import numpy as np
import requests
from rasterio.errors import NotGeoreferencedWarning
from rasterio.features import shapes
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from shapely.geometry import shape
from shapely.ops import unary_union

PIXEL_M = 3.0

# Exported PNGs carry no georeferencing; the transform is computed from the bbox.
warnings.filterwarnings("ignore", category=NotGeoreferencedWarning)


def _get_json(url: str, **params) -> dict:
    resp = requests.get(url, params={"f": "json", **params}, timeout=180)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(data["error"])
    return data


MAX_DATUM_DISAGREEMENT_FT = 0.5  # USGS gauge datum vs the library's own zero datum
# A library resolves stage only if its extent grows with it. Refused when the lowest layer already covers this share
# of the top layer's extent. A coarse check, not calibrated: Harvey's libraries are 0.12 (HGTT2) and 0.02 (GBHT2);
# BLTN7 (Swannanoa) is 0.97, mapping 1.05 km2 at least 1 ft deep at a gage height of 3.6 ft (base flow 1.9 ft).
MAX_LOWEST_TO_TOP_EXTENT = 0.9


class LibraryRefused(ValueError):
    """The library can't be used for this gauge; the river driver falls back to HAND and says why."""


class LibraryDatumError(LibraryRefused):
    """The library's water-surface elevations can't be converted to this gauge's stage with confidence."""


def check_resolves_stage(fim: gpd.GeoDataFrame, site_id: str, lid: str) -> None:
    """Refuse a library whose extent barely changes across its range: it can't say what floods at a given stage."""
    areas = fim.sort_values("stage_ft").geometry.area.to_numpy()
    ratio = areas[0] / areas[-1]
    if ratio >= MAX_LOWEST_TO_TOP_EXTENT:
        raise LibraryRefused(
            f"the NWS flood-map library ({lid}) does not resolve stage: its lowest layer "
            f"({fim.stage_ft.min():.2f} ft) already maps {ratio:.0%} of its highest layer's extent "
            f"({fim.stage_ft.max():.2f} ft), so it would flood the same area near base flow as at its top")


def in_gauge_stage(fim: gpd.GeoDataFrame, site_id: str, gauge_datum_ft: Optional[float],
                   gauge_vertical_datum: Optional[str], library_zero_ft: Optional[float]) -> gpd.GeoDataFrame:
    """The library with stage_ft in the gauge's own stage (ft above the USGS gauge datum), so it compares directly
    with USGS gage height; wse_ft keeps the layer's water-surface elevation. The USGS datum is used because the
    stage readings are USGS's; NWS's own zero datum for the library, when published, must agree with it."""
    if gauge_vertical_datum != "NAVD88" or gauge_datum_ft is None:
        raise LibraryDatumError(f"USGS {site_id}: gauge datum is {gauge_datum_ft} {gauge_vertical_datum}, not NAVD88; "
                                f"the library's NAVD88 water-surface elevations can't be converted to stage")
    if library_zero_ft is not None and abs(library_zero_ft - gauge_datum_ft) > MAX_DATUM_DISAGREEMENT_FT:
        raise LibraryDatumError(f"USGS {site_id}: the library's zero datum ({library_zero_ft} ft) and the USGS gauge "
                                f"datum ({gauge_datum_ft} ft) differ by more than {MAX_DATUM_DISAGREEMENT_FT} ft")
    out = fim.rename(columns={"stage_ft": "wse_ft"})
    out.insert(0, "stage_ft", (out["wse_ft"] - gauge_datum_ft).round(2))
    return out


def fetch_fim_extents(mapserver_url: str) -> gpd.GeoDataFrame:
    """One inundation-extent geometry per library layer, EPSG:4326, sorted by its water-surface elevation. The column
    is named stage_ft but holds the layer name (ft NAVD88) until in_gauge_stage converts it."""
    service = _get_json(mapserver_url)
    stage_layers = []
    for layer in service["layers"]:
        try:
            stage_layers.append((layer["id"], float(layer["name"])))
        except ValueError:
            continue
    if not stage_layers:
        raise RuntimeError(f"No stage layers in {mapserver_url}")

    extents = [_get_json(f"{mapserver_url}/{layer_id}")["extent"] for layer_id, _ in stage_layers]
    wkid = extents[0]["spatialReference"].get("latestWkid") or extents[0]["spatialReference"]["wkid"]
    xmin = min(e["xmin"] for e in extents) - 50
    ymin = min(e["ymin"] for e in extents) - 50
    xmax = max(e["xmax"] for e in extents) + 50
    ymax = max(e["ymax"] for e in extents) + 50
    width, height = int((xmax - xmin) / PIXEL_M), int((ymax - ymin) / PIXEL_M)
    transform = from_bounds(xmin, ymin, xmax, ymax, width, height)

    records = []
    for layer_id, stage_ft in stage_layers:
        resp = requests.get(
            f"{mapserver_url}/export",
            params={
                "bbox": f"{xmin},{ymin},{xmax},{ymax}", "bboxSR": wkid, "imageSR": wkid,
                "size": f"{width},{height}", "layers": f"show:{layer_id}", "format": "png32",
                "transparent": "true", "dpi": 96, "f": "image",
            },
            timeout=300,
        )
        resp.raise_for_status()
        with MemoryFile(resp.content) as mem, mem.open() as img:
            if img.count != 4:
                raise RuntimeError(f"layer {layer_id}: expected RGBA PNG, got {img.count} bands")
            alpha = img.read(4)
        wet = (alpha > 0).astype("uint8")
        polygons = [shape(g) for g, value in shapes(wet, mask=wet == 1, transform=transform) if value == 1]
        records.append({"stage_ft": stage_ft, "geometry": unary_union(polygons)})
    gdf = gpd.GeoDataFrame(records, crs=wkid).to_crs(4326)
    return gdf.sort_values("stage_ft").reset_index(drop=True)


def iou(a: np.ndarray, b: np.ndarray) -> float:
    union = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / union) if union else float("nan")
