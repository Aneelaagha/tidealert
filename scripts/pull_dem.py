"""Download a USGS 3DEP DEM (~10 m, meters NAVD88) for the White Oak Bayou corridor.

Uses the 3DEP ImageServer's exportImage, reprojected to UTM 15N (EPSG:32615),
which is the CRS the isolation engine samples node elevations in.

Usage (from the repo root):
    .venv/bin/python scripts/pull_dem.py
"""
import os

import requests

URL = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage"
# Same (west, south, east, north) bbox as scripts/pull_osm_roads.py.
BBOX = (-95.50, 29.74, -95.36, 29.87)
SIZE = (1400, 1450)  # ~10 m pixels over the bbox
OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "backend", "app", "data", "dem_3dep_10m.tif")


def main() -> None:
    resp = requests.get(
        URL,
        params={
            "bbox": ",".join(map(str, BBOX)),
            "bboxSR": 4326,
            "imageSR": 32615,
            "size": f"{SIZE[0]},{SIZE[1]}",
            "format": "tiff",
            "pixelType": "F32",
            "interpolation": "RSP_BilinearInterpolation",
            "f": "image",
        },
        timeout=600,
    )
    resp.raise_for_status()
    if not resp.content.startswith((b"II*\x00", b"MM\x00*")):
        raise RuntimeError(f"3DEP did not return a GeoTIFF: {resp.content[:200]!r}")
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "wb") as f:
        f.write(resp.content)
    print(f"Wrote {len(resp.content) / 1e6:.1f} MB to {OUT_PATH}")


if __name__ == "__main__":
    main()
