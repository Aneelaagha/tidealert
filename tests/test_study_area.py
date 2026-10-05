"""Study-area clips (app.services.study_area): only registered gauges are clipped, the cut is stated, the clip
excludes other gauges' basins, and the cached polygon makes reruns model the same area. No network: the place
boundary and the other basins are injected."""
from shapely.geometry import box

from app.services import study_area
from app.services.study_area import CLIPS

BASIN = box(0, 0, 10, 10)  # the gauge's full basin
CITY = box(2, 2, 8, 8)  # the place boundary
OTHER = box(6, 0, 10, 10)  # another gauge's basin, overlapping the city


def place(_geoid):
    return CITY


def basin_of(_site):
    return OTHER


def test_unregistered_gauges_keep_their_whole_basin(tmp_path):
    for site in ("08074500", "08076000", "08075770", "03451000"):  # Harvey's three, and the Swannanoa
        clipped, study = study_area.apply(site, BASIN, basin_of, place, cache_dir=str(tmp_path / site))
        assert clipped.equals(BASIN) and study is None
        assert not (tmp_path / site).exists()  # nothing cached for an unclipped gauge


def test_the_french_broad_is_clipped_to_the_city_minus_the_swannanoa(tmp_path):
    clipped, study = study_area.apply("03451500", BASIN, basin_of, place, cache_dir=str(tmp_path))
    assert clipped.equals(box(2, 2, 6, 8))  # city ∩ basin, minus the other basin
    assert clipped.intersection(OTHER).area == 0  # disjoint from the excluded basin: no zone modelled twice
    assert study.full_basin.equals(BASIN)
    assert "Asheville city" in study.note and "03451000" in study.note and "only street blocks inside it" in study.note
    assert CLIPS["03451500"].exclude_basins_of == ("03451000",)


def test_the_clip_is_cached_so_reruns_model_the_same_area(tmp_path):
    first, _ = study_area.apply("03451500", BASIN, basin_of, place, cache_dir=str(tmp_path))
    assert (tmp_path / "study_area.json").exists()

    def no_network(_):
        raise AssertionError("the cached clip should be used")
    again, study = study_area.apply("03451500", BASIN, no_network, no_network, cache_dir=str(tmp_path))
    assert again.equals(first) and study is not None


def test_an_empty_clip_is_refused(tmp_path):
    import pytest
    with pytest.raises(RuntimeError, match="empty"):
        study_area.apply("03451500", BASIN, lambda _: BASIN, place, cache_dir=str(tmp_path))


# ---------------------------------------------------------------- the 3DEP retry (no network)
class _Resp:
    def __init__(self, code):
        self.status_code, self.content = code, b"II*\x00"

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(str(self.status_code))


def _fake_get(codes, calls):
    def get(url, params=None, timeout=None):
        calls.append(url)
        code = codes.pop(0)
        if code == "conn":
            import requests
            raise requests.ConnectionError("reset")
        return _Resp(code)
    return get


def test_dem_download_retries_transient_failures_then_succeeds(monkeypatch):
    from app.services import terrain
    calls, waits = [], []
    monkeypatch.setattr(terrain.requests, "get", _fake_get([502, "conn", 200], calls))
    resp = terrain._get_with_retry("u", {}, "x", sleep=waits.append)
    assert resp.status_code == 200 and len(calls) == 3 and waits == [10.0, 30.0]


def test_dem_download_gives_up_after_three_attempts_and_never_retries_a_client_error(monkeypatch):
    import pytest
    import requests
    from app.services import terrain
    calls = []
    monkeypatch.setattr(terrain.requests, "get", _fake_get([500, 502, 503], calls))
    with pytest.raises(requests.HTTPError):
        terrain._get_with_retry("u", {}, "x", sleep=lambda s: None)
    assert len(calls) == 3
    calls.clear()
    monkeypatch.setattr(terrain.requests, "get", _fake_get([400], calls))
    with pytest.raises(requests.HTTPError):
        terrain._get_with_retry("u", {}, "x", sleep=lambda s: None)
    assert len(calls) == 1  # a bad request is not retried
