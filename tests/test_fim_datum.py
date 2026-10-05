"""NWS flood-map library layers are water-surface elevations (ft NAVD88); app.services.fim_library.in_gauge_stage
converts them to gauge stage. No network: libraries are built in memory."""
import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import box

from app.services.fim_library import LibraryDatumError, LibraryRefused, check_resolves_stage, in_gauge_stage
from app.services.gauge_site import _fim_zero_datum
from app.services.river_driver import library_level


def library(names):
    return gpd.GeoDataFrame({"stage_ft": names, "geometry": [box(0, 0, i + 1, 1) for i in range(len(names))]},
                            crs=4326)


def test_layers_are_converted_with_the_usgs_gauge_datum():
    fim = in_gauge_stage(library([1980.0, 1988.0, 1996.0]), "03451000", 1976.37, "NAVD88", 1976.29)
    assert list(fim.stage_ft) == [3.63, 11.63, 19.63] and list(fim.wse_ft) == [1980.0, 1988.0, 1996.0]


def test_a_library_on_a_zero_datum_gauge_is_unchanged():
    """Harvey: White Oak and Greens Bayou have a gauge datum of 0.0 ft, so the conversion changes nothing there."""
    names = [52.4, 53.4, 54.4]
    assert list(in_gauge_stage(library(names), "08076000", 0.0, "NAVD88", 0.007).stage_ft) == names


def test_the_swannanoa_peak_reaches_the_top_layer_instead_of_flooding_nothing():
    raw = library([1980.0 + 0.5 * i for i in range(33)])  # BLTN7: 1,980-1,996 ft
    peak_stage = np.array([27.33])  # USGS gage height, 2024-09-27 19:00 UTC
    assert library_level(np.sort(raw.stage_ft.to_numpy()), peak_stage)[0] == -np.inf  # the bug: below every layer
    fim = in_gauge_stage(raw, "03451000", 1976.37, "NAVD88", 1976.29)
    assert library_level(np.sort(fim.stage_ft.to_numpy()), peak_stage)[0] == pytest.approx(1996.0 - 1976.37)


def test_a_library_is_refused_when_the_datums_cannot_be_reconciled():
    with pytest.raises(LibraryDatumError, match="not NAVD88"):
        in_gauge_stage(library([10.0]), "x", 3.2, "NGVD29", None)
    with pytest.raises(LibraryDatumError, match="not NAVD88"):
        in_gauge_stage(library([10.0]), "x", None, "NAVD88", None)
    with pytest.raises(LibraryDatumError, match="differ by more than"):
        in_gauge_stage(library([1980.0]), "x", 1976.37, "NAVD88", 1970.0)


def test_the_library_zero_datum_is_read_only_when_it_is_navd88():
    assert _fim_zero_datum({"zeroDatum": {"value": 1976.29, "datum": "NAVD88"}}) == 1976.29
    assert _fim_zero_datum({"zeroDatum": {"value": 0, "datum": "NAVD88"}}) == 0.0
    assert _fim_zero_datum({"zeroDatum": {"value": 12.0, "datum": "NGVD29"}}) is None
    assert _fim_zero_datum({}) is None


# ---------------------------------------------------------------- a library must resolve stage
def nested(areas):
    """A library whose layers are nested squares of the given areas (m2), in a metric CRS."""
    return gpd.GeoDataFrame({"stage_ft": [float(i) for i in range(len(areas))],
                             "geometry": [box(0, 0, a ** 0.5, a ** 0.5) for a in areas]}, crs=32617)


def test_a_library_that_grows_with_stage_is_kept():
    check_resolves_stage(nested([0.26, 1.0, 2.25]), "08074500", "HGTT2")  # like HGTT2: lowest/top 0.12
    check_resolves_stage(nested([0.16, 7.03]), "08076000", "GBHT2")  # like GBHT2: 0.02


def test_a_library_whose_extent_barely_changes_is_refused_with_the_reason():
    with pytest.raises(LibraryRefused, match="does not resolve stage: its lowest layer .* 97% of its highest"):
        check_resolves_stage(nested([1.054, 1.06, 1.085]), "03451000", "BLTN7")  # like BLTN7: 0.97


def test_a_refused_library_falls_back_to_hand_and_the_caveat_says_why(monkeypatch):
    from types import SimpleNamespace
    from app.services import river_driver
    site = SimpleNamespace(site_id="03451000", comid=1, nws_lid="BLTN7", fim_mapserver_url="u",
                           gauge_datum_altitude_ft=1976.37, gauge_vertical_datum="NAVD88", fim_zero_datum_ft=1976.29)
    raw = nested([1.054, 1.06, 1.085])
    raw["stage_ft"] = [1980.0, 1988.0, 1996.0]
    monkeypatch.setattr(river_driver, "fetch_fim_extents", lambda url: raw.to_crs(4326))
    fim, refused = river_driver.load_fim_library(site, 32617)
    assert fim is None and "BLTN7" in refused and "does not resolve stage" in refused
    monkeypatch.setattr(river_driver, "gauge_nhd_reach", lambda s, t: np.ones((1, 1), bool))
    terrain = SimpleNamespace(mainstem_drain=np.zeros((1, 1), int), hand_mainstem=np.zeros((1, 1)))
    river = river_driver.build_river_driver(site, terrain, None, np.zeros(1), fim, refused)
    assert river.confidence == "LOWER CONFIDENCE"
    assert "publishes a flood-map library for USGS 03451000 but it was refused" in river.caveat


def test_a_gauge_with_no_library_keeps_its_caveat_word_for_word(monkeypatch):
    """Hunting Bayou (Harvey) has no library: its caveat text, which Cases quote, must not change."""
    from types import SimpleNamespace
    from app.services import river_driver
    monkeypatch.setattr(river_driver, "gauge_nhd_reach", lambda s, t: np.ones((1, 1), bool))
    site = SimpleNamespace(site_id="08075770", comid=1)
    terrain = SimpleNamespace(mainstem_drain=np.zeros((1, 1), int), hand_mainstem=np.zeros((1, 1)))
    river = river_driver.build_river_driver(site, terrain, None, np.zeros(1), None)
    assert river.caveat == ("River flooding from HAND (height above nearest drainage, snapped channel) because NWS "
                            "publishes no flood-map library for USGS 08075770; assumes constant depth along the reach. "
                            "Lower confidence.")
