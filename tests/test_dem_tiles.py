"""Tiled 3DEP download (app.services.terrain._download_tiled). No network: a fake 3DEP returns GeoTIFFs whose cell
values encode each cell's position on the full grid, so a misplaced, missing or overlapping tile shows."""
import numpy as np
import pytest
import rasterio
from rasterio.transform import Affine

from app.services import terrain

XMIN, YTOP, RES = 500_000.0, 4_000_000.0, 10.0


class _Resp:
    def __init__(self, content):
        self.content = content


def fake_3dep(requests_seen, shrink=False):
    def get(url, params, site_id):
        x0, y0, x1, y1 = map(float, params["bbox"].split(","))
        w, h = map(int, params["size"].split(","))
        requests_seen.append((w, h))
        col0, row0 = round((x0 - XMIN) / RES), round((YTOP - y1) / RES)
        rows, cols = np.mgrid[row0:row0 + h, col0:col0 + w]
        data = (rows * 10_000 + cols).astype(np.float32)
        if shrink:
            data = data[:-1]
        with rasterio.MemoryFile() as mem:
            with mem.open(driver="GTiff", width=data.shape[1], height=data.shape[0], count=1, dtype="float32",
                          crs="EPSG:32617", transform=Affine(RES, 0, x0, 0, -RES, y1)) as dst:
                dst.write(data, 1)
            return _Resp(mem.read())
    return get


def test_tiles_are_stitched_on_the_full_grid_with_no_gap_or_overlap(tmp_path, monkeypatch):
    monkeypatch.setattr(terrain, "DEM_TILE_PIXELS", 100)
    seen, out = [], str(tmp_path / "dem.tif")
    terrain._download_tiled(XMIN, YTOP, 250, 130, RES, 32617, "x", out, get=fake_3dep(seen))
    assert sorted(seen) == sorted([(100, 100), (100, 100), (50, 100), (100, 30), (100, 30), (50, 30)])
    with rasterio.open(out) as src:
        rows, cols = np.mgrid[0:130, 0:250]
        assert (src.read(1) == rows * 10_000 + cols).all()  # every cell from the right place on the full grid
        assert src.transform == Affine(RES, 0, XMIN, 0, -RES, YTOP) and src.crs.to_epsg() == 32617


def test_a_tile_of_the_wrong_size_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(terrain, "DEM_TILE_PIXELS", 100)
    with pytest.raises(RuntimeError, match="expected"):
        terrain._download_tiled(XMIN, YTOP, 150, 50, RES, 32617, "x", str(tmp_path / "d.tif"),
                                get=fake_3dep([], shrink=True))


def test_a_grid_within_the_limit_is_still_one_request_and_a_larger_one_is_tiled(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from shapely.geometry import Point
    calls = []
    monkeypatch.setattr(terrain, "_export", lambda *a, **k: calls.append(("one", a[2], a[3])) or b"II*\x00")
    monkeypatch.setattr(terrain, "_download_tiled", lambda *a, **k: calls.append(("tiled", a[2], a[3])))
    centre = Point(-82.5, 35.6)
    for km in (5, 30):  # basins about 5 km and 30 km across (plus the 1 km buffer), at 10 m
        site = SimpleNamespace(site_id="x", point=centre, basin=centre.buffer(km / 222))
        (tmp_path / f"{km}.tif.tmp").write_bytes(b"")  # what the stubbed _download_tiled would have written
        terrain.download_dem(site, str(tmp_path / f"{km}.tif"))
    assert calls[0][0] == "one" and max(calls[0][1:]) <= terrain.DEM_TILE_PIXELS
    assert calls[1][0] == "tiled" and max(calls[1][1:]) > terrain.DEM_TILE_PIXELS
    assert terrain.DEM_TILE_PIXELS == 2000  # the Swannanoa's 2,861 x 2,691 single export failed; 2,401 x 1,690 worked
