"""Sentinel-1 flood change detection, for validating modeled flood extents.

Reads Sentinel-1 radiometrically terrain-corrected (RTC) VV backscatter from
Microsoft Planetary Computer (anonymous SAS token, 10 m) and flags new open
water with the standard change rule:

    post_db <= OPEN_WATER_DB  and  post_db - pre_db <= CHANGE_DB

after 3x3 boxcar speckle smoothing in linear power. Pairs are found
automatically: every scene acquired during the event is paired with the
latest earlier scene on the same relative orbit (same viewing geometry)
from before the event.

Known blind spot: floodwater among buildings raises backscatter (double
bounce) instead of lowering it, so flooded urban blocks are largely missed.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import rasterio
import requests
from affine import Affine
from rasterio.warp import Resampling, reproject, transform_bounds
from rasterio.windows import from_bounds

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
TOKEN_URL = "https://planetarycomputer.microsoft.com/api/sas/v1/token/sentinel-1-rtc"
COLLECTION = "sentinel-1-rtc"
OPEN_WATER_DB = -15.0
CHANGE_DB = -3.0
MAX_PRE_EVENT_LOOKBACK = timedelta(days=60)


@dataclass
class Scene:
    item_id: str
    acquired_at: datetime
    relative_orbit: int
    orbit_state: str
    vv_db: np.ndarray
    transform: Affine
    crs: rasterio.crs.CRS


def _search(bbox: tuple[float, float, float, float], start: datetime, end: datetime) -> list[dict]:
    resp = requests.post(
        f"{STAC_URL}/search",
        json={"collections": [COLLECTION], "bbox": list(bbox),
              "datetime": f"{start:%Y-%m-%dT%H:%M:%SZ}/{end:%Y-%m-%dT%H:%M:%SZ}", "limit": 200},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["features"]


def _acquired(item: dict) -> datetime:
    return datetime.fromisoformat(item["properties"]["datetime"].replace("Z", "+00:00"))


def _passes(items: list[dict]) -> dict[tuple, list[dict]]:
    """Group items into satellite passes: adjacent frames share platform, relative orbit and day."""
    passes: dict[tuple, list[dict]] = {}
    for item in items:
        p = item["properties"]
        passes.setdefault((p["platform"], p["sat:relative_orbit"], _acquired(item).date()), []).append(item)
    return passes


def find_pairs(bbox: tuple[float, float, float, float], start: datetime, end: datetime) -> list[tuple[list[str], list[str]]]:
    """(pre_ids, post_ids) per event pass: the pass's frames, and the frames of the latest pre-event
    pass on the same relative orbit."""
    during = _passes(_search(bbox, start, end))
    before = _passes(_search(bbox, start - MAX_PRE_EVENT_LOOKBACK, start))
    pairs = []
    for key, post_items in sorted(during.items(), key=lambda kv: min(_acquired(i) for i in kv[1])):
        candidates = [k for k in before if k[1] == key[1]]
        if candidates:
            pre_key = max(candidates, key=lambda k: max(_acquired(i) for i in before[k]))
            pairs.append(([i["id"] for i in before[pre_key]], [i["id"] for i in post_items]))
    return pairs


def _boxcar3(power: np.ndarray) -> np.ndarray:
    padded = np.pad(power, 1, mode="edge")
    windows = [padded[1 + dy : 1 + dy + power.shape[0], 1 + dx : 1 + dx + power.shape[1]]
               for dy in (-1, 0, 1) for dx in (-1, 0, 1)]
    return np.mean(windows, axis=0)


def load_scene(item_id: str, bbox_4326: tuple[float, float, float, float]) -> Scene:
    item = requests.get(f"{STAC_URL}/collections/{COLLECTION}/items/{item_id}", timeout=60).json()
    token = requests.get(TOKEN_URL, timeout=60).json()["token"]
    with rasterio.open(f"{item['assets']['vv']['href']}?{token}") as src:
        bounds = transform_bounds(4326, src.crs, *bbox_4326)
        window = from_bounds(*bounds, transform=src.transform).round_offsets().round_lengths()
        power = src.read(1, window=window, boundless=True, fill_value=0).astype(float)
        transform, crs = src.window_transform(window), src.crs
    power[power <= 0] = np.nan
    props = item["properties"]
    return Scene(
        item_id=item_id,
        acquired_at=_acquired(item),
        relative_orbit=props["sat:relative_orbit"],
        orbit_state=props["sat:orbit_state"],
        vv_db=10 * np.log10(_boxcar3(power)),
        transform=transform,
        crs=crs,
    )


def load_pass(item_ids: list[str], bbox_4326: tuple[float, float, float, float]) -> Scene:
    """Mosaic the frames of one pass onto the first frame's grid (frames only fill each other's gaps)."""
    scenes = [load_scene(i, bbox_4326) for i in item_ids]
    base = scenes[0]
    mosaic = base.vv_db.copy()
    for other in scenes[1:]:
        if other.vv_db.shape == base.vv_db.shape and other.transform == base.transform and other.crs == base.crs:
            on_base = other.vv_db
        else:
            on_base = np.full(base.vv_db.shape, np.nan)
            reproject(other.vv_db, on_base, src_transform=other.transform, src_crs=other.crs, src_nodata=np.nan,
                      dst_transform=base.transform, dst_crs=base.crs, dst_nodata=np.nan,
                      resampling=Resampling.bilinear)
        mosaic = np.where(np.isnan(mosaic), on_base, mosaic)
    return Scene(
        item_id="+".join(item_ids),
        acquired_at=min(s.acquired_at for s in scenes),
        relative_orbit=base.relative_orbit,
        orbit_state=base.orbit_state,
        vv_db=mosaic,
        transform=base.transform,
        crs=base.crs,
    )


def new_water(pre: Scene, post: Scene) -> tuple[np.ndarray, np.ndarray]:
    """New-open-water mask on the post scene's grid, and the pre scene's dB resampled onto that grid
    (use it, not pre.vv_db, for validity masks)."""
    if pre.relative_orbit != post.relative_orbit:
        raise ValueError(f"orbit mismatch: {pre.relative_orbit} vs {post.relative_orbit}")
    pre_db = pre.vv_db
    if pre.vv_db.shape != post.vv_db.shape or pre.transform != post.transform or pre.crs != post.crs:
        pre_db = np.full(post.vv_db.shape, np.nan)
        reproject(pre.vv_db, pre_db, src_transform=pre.transform, src_crs=pre.crs, src_nodata=np.nan,
                  dst_transform=post.transform, dst_crs=post.crs, dst_nodata=np.nan, resampling=Resampling.bilinear)
    return (post.vv_db <= OPEN_WATER_DB) & (post.vv_db - pre_db <= CHANGE_DB), pre_db
