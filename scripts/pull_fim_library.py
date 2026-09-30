"""Download the NWS Flood Inundation Mapping library for HGTT2 (USGS 08074500).

The NWS FIM library is a set of pre-computed inundation depth grids, one per
1 ft of stage (21.7 .. 45.7 ft, gauge datum 0 ft NAVD88), published as raster
layers on an ArcGIS MapServer. The bulk-download zip linked from the NWPS
gauge page 404s, so each stage layer is rendered as a transparent PNG at
~3 m/pixel and every painted pixel is treated as wet. The result is one
inundation-extent (multi)polygon per stage plus the library's study boundary,
written to backend/app/data/fim_hgtt2/fim_extents.gpkg.

Usage (from the repo root):
    .venv/bin/python scripts/pull_fim_library.py
"""
import os
import warnings

import geopandas as gpd
import requests
from rasterio.features import shapes
from rasterio.errors import NotGeoreferencedWarning
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from shapely.geometry import shape
from shapely.ops import unary_union

MAPSERVER = "https://mapservices.weather.noaa.gov/static/rest/services/NWS_FIM/FIM_hgtt2/MapServer"
OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "backend", "app", "data", "fim_hgtt2", "fim_extents.gpkg")
STUDY_BOUNDARY_LAYER = 27
PIXEL_M = 3.0

# Exported PNGs carry no georeferencing; the transform is computed from the bbox.
warnings.filterwarnings("ignore", category=NotGeoreferencedWarning)


def get_json(url: str, **params) -> dict:
    resp = requests.get(url, params={"f": "json", **params}, timeout=180)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(data["error"])
    return data


def main() -> None:
    service = get_json(MAPSERVER)
    stage_layers = []
    for layer in service["layers"]:
        try:
            stage_layers.append((layer["id"], float(layer["name"])))
        except ValueError:
            continue
    print(f"{len(stage_layers)} stage layers: {stage_layers[0][1]} .. {stage_layers[-1][1]} ft")

    # Render every layer over the union of their extents (EPSG:3857).
    extents = [get_json(f"{MAPSERVER}/{layer_id}")["extent"] for layer_id, _ in stage_layers]
    xmin = min(e["xmin"] for e in extents) - 50
    ymin = min(e["ymin"] for e in extents) - 50
    xmax = max(e["xmax"] for e in extents) + 50
    ymax = max(e["ymax"] for e in extents) + 50
    width = int((xmax - xmin) / PIXEL_M)
    height = int((ymax - ymin) / PIXEL_M)
    transform = from_bounds(xmin, ymin, xmax, ymax, width, height)

    records = []
    for layer_id, stage_ft in stage_layers:
        resp = requests.get(
            f"{MAPSERVER}/export",
            params={
                "bbox": f"{xmin},{ymin},{xmax},{ymax}",
                "bboxSR": 3857,
                "imageSR": 3857,
                "size": f"{width},{height}",
                "layers": f"show:{layer_id}",
                "format": "png32",
                "transparent": "true",
                "dpi": 96,
                "f": "image",
            },
            timeout=300,
        )
        resp.raise_for_status()
        with MemoryFile(resp.content) as mem, mem.open() as img:
            if img.count != 4:
                raise RuntimeError(f"layer {layer_id}: expected RGBA PNG, got {img.count} bands")
            alpha = img.read(4)
        if alpha.shape != (height, width):
            raise RuntimeError(f"layer {layer_id}: got image {alpha.shape}, expected {(height, width)}")
        wet = (alpha > 0).astype("uint8")
        polygons = [shape(geom) for geom, value in shapes(wet, mask=wet == 1, transform=transform) if value == 1]
        extent = unary_union(polygons)
        records.append({"stage_ft": stage_ft, "layer_id": layer_id, "wet_pixels": int(wet.sum()), "geometry": extent})
        print(f"  stage {stage_ft:5.1f} ft: {extent.area / 1e6:.3f} km2 (web-mercator area)")

    extents_gdf = gpd.GeoDataFrame(records, crs=3857).to_crs(4326)

    boundary = requests.get(
        f"{MAPSERVER}/{STUDY_BOUNDARY_LAYER}/query",
        params={"where": "1=1", "outSR": 4326, "f": "geojson"},
        timeout=180,
    ).json()
    boundary_gdf = gpd.GeoDataFrame.from_features(boundary["features"], crs=4326)

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    extents_gdf.to_file(OUT_PATH, layer="inundation_extents", driver="GPKG")
    boundary_gdf.to_file(OUT_PATH, layer="study_boundary", driver="GPKG")
    print(f"Wrote {len(extents_gdf)} stage extents and {len(boundary_gdf)} study boundary feature(s) to {OUT_PATH}")


if __name__ == "__main__":
    main()
