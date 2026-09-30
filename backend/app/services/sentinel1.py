"""Sentinel-1 flood change detection over a small area, for validating FIM extents.

Reads Sentinel-1 radiometrically terrain-corrected (RTC) VV backscatter from
Microsoft Planetary Computer (anonymous SAS token, 10 m, UTM 15N) and flags
new open water with the standard change rule:

    post_db <= OPEN_WATER_DB  and  post_db - pre_db <= CHANGE_DB

after 3x3 boxcar speckle smoothing in linear power. Pre and post scenes must
share a relative orbit so viewing geometry matches.

Known blind spot: floodwater among buildings raises backscatter (double
bounce) instead of lowering it, so flooded urban blocks are largely missed.
"""
from dataclasses import dataclass

import numpy as np
import rasterio
import requests
from affine import Affine
from rasterio.windows import from_bounds

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
TOKEN_URL = "https://planetarycomputer.microsoft.com/api/sas/v1/token/sentinel-1-rtc"
OPEN_WATER_DB = -15.0
CHANGE_DB = -3.0


@dataclass
class Scene:
    item_id: str
    acquired_at: str
    relative_orbit: int
    orbit_state: str
    vv_db: np.ndarray
    transform: Affine


def _boxcar3(power: np.ndarray) -> np.ndarray:
    padded = np.pad(power, 1, mode="edge")
    windows = [padded[1 + dy : 1 + dy + power.shape[0], 1 + dx : 1 + dx + power.shape[1]]
               for dy in (-1, 0, 1) for dx in (-1, 0, 1)]
    return np.mean(windows, axis=0)


def load_scene(item_id: str, bounds_utm: tuple[float, float, float, float]) -> Scene:
    item = requests.get(f"{STAC_URL}/collections/sentinel-1-rtc/items/{item_id}", timeout=60).json()
    token = requests.get(TOKEN_URL, timeout=60).json()["token"]
    with rasterio.open(f"{item['assets']['vv']['href']}?{token}") as src:
        if src.crs.to_epsg() != 32615:
            raise ValueError(f"{item_id}: expected EPSG:32615, got {src.crs}")
        window = from_bounds(*bounds_utm, transform=src.transform).round_offsets().round_lengths()
        power = src.read(1, window=window).astype(float)
        transform = src.window_transform(window)
    power[power <= 0] = np.nan
    props = item["properties"]
    return Scene(
        item_id=item_id,
        acquired_at=props["datetime"],
        relative_orbit=props["sat:relative_orbit"],
        orbit_state=props["sat:orbit_state"],
        vv_db=10 * np.log10(_boxcar3(power)),
        transform=transform,
    )


def new_water(pre: Scene, post: Scene) -> np.ndarray:
    if pre.relative_orbit != post.relative_orbit:
        raise ValueError(f"orbit mismatch: {pre.relative_orbit} vs {post.relative_orbit}")
    if pre.vv_db.shape != post.vv_db.shape or pre.transform != post.transform:
        raise ValueError("pre/post scenes are not on the same grid")
    return (post.vv_db <= OPEN_WATER_DB) & (post.vv_db - pre.vv_db <= CHANGE_DB)
