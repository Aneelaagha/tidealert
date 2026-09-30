"""Read an NWS Flood Inundation Mapping (FIM) library, where NWS publishes one for a gauge.

A FIM library is a set of pre-computed inundation depth grids, one per stage
(ft, gauge datum), published as raster layers on an ArcGIS MapServer (URL
from the NWPS gauge record). The bulk-download zips linked from NWPS are not
reliably available, so each stage layer is rendered as a transparent PNG at
PIXEL_M and every painted pixel is treated as wet. Rendering was checked
against the vector flood-category polygons of the HGTT2 library
(IoU 0.95-0.97).
"""
import warnings

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


def fetch_fim_extents(mapserver_url: str) -> gpd.GeoDataFrame:
    """One inundation-extent geometry per library stage, EPSG:4326, sorted by stage_ft."""
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
