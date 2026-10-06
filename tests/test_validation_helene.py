"""The Helene (Asheville, 2024) results in the validation panel, pinned to their stored files and to the numbers written
in docs/regions/helene.md, the way the Harvey results are (tests/test_validation.py)."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOC = (ROOT / "docs" / "regions" / "helene.md").read_text()


@pytest.fixture(scope="module")
def v(client):
    r = client.get("/validation/helene")
    assert r.status_code == 200, r.text
    return r.json()


def by_site(v):
    return {g["site"]: g for g in v["gauges"]}


def test_it_names_the_run_the_event_and_the_window(v):
    assert v["run"] == "backtest:2024-09-25..2024-09-30" and v["event"] == "Hurricane Helene"
    assert v["data_window_utc"][0].startswith("2024-09-25") and v["data_window_utc"][1].startswith("2024-10-01")


def test_each_gauge_row_is_the_stored_value_in_the_named_file(v):
    for g in v["gauges"]:
        stored = json.loads((ROOT / g["source"]["file"]).read_text())
        assert g["zones"] == {k: stored["zone_status"][k] for k in ("isolated", "possibly isolated", "reachable", "not connected at base flow")}
        assert g["first_road_floods_min"] == round(stored["lead_minutes_vs_alarm"]["first road segment floods"])
        assert g["roads_ever_flooded"] == stored["flooded_edges_max"] and g["roads_flooding_unknown"] == stored["unknown_river_segments"]
        assert g["nfip_claims_total"] == sum(stored["claims_daily"].values())
        assert g["stage_steps"]["missing"] == stored["stage_provenance"].get("missing", 0)
        assert g["rain_driver_evaluated"] is False and "2020-12-31" in g["rainfall"]  # the rainfall source ends before the event
        assert g["confidence"] == "LOWER CONFIDENCE" and "HAND" in g["flood_source"]


def test_the_numbers_match_the_region_doc(v):
    s, f = by_site(v)["03451000"], by_site(v)["03451500"]
    # Swannanoa
    assert "512 zones, 29,440 people" in DOC and (s["zones"]["possibly isolated"]["zones"], s["zones"]["possibly isolated"]["people"]) == (512, 29440)
    assert "148 zones, 10,075 people" in DOC and (s["zones"]["reachable"]["zones"], s["zones"]["reachable"]["people"]) == (148, 10075)
    assert "399 measured, 28 from the rating curve, **150 missing**" in DOC
    assert (s["stage_steps"]["measured"], s["stage_steps"]["from_rating_curve"], s["stage_steps"]["missing"]) == (399, 28, 150)
    assert "234 min after the minor-flood alarm" in DOC and s["first_road_floods_min"] == 234
    assert "**48**" in DOC and s["roads_ever_flooded"] == 48
    assert "294 in total; 233 on 27 Sep" in DOC and (s["nfip_claims_total"], s["nfip_peak_day"], s["nfip_peak_day_claims"]) == (294, "2024-09-27", 233)
    # French Broad
    assert "170 zones, 8,160 people" in DOC and (f["zones"]["possibly isolated"]["zones"], f["zones"]["possibly isolated"]["people"]) == (170, 8160)
    assert "243 zones, 15,112 people" in DOC and "142 zones, 8,629 people" in DOC
    assert (f["zones"]["reachable"]["zones"], f["zones"]["not connected at base flow"]["zones"]) == (243, 142)
    assert "1,756 min after the alarm" in DOC and f["first_road_floods_min"] == -1756
    assert "73 in total; 59 on 27 Sep" in DOC and (f["nfip_claims_total"], f["nfip_peak_day_claims"]) == (73, 59)


def test_no_zone_is_confirmed_isolated_and_the_headline_says_it_does_not_validate_the_engine(v):
    assert all(g["zones"]["isolated"] == {"zones": 0, "people": 0} for g in v["gauges"])
    text = {h["kind"]: h["text"] for h in v["headline"]}
    assert "does not validate the engine" in text["weakness"] and "no Case opened" in text["weakness"]
    assert "cannot separate those causes" in text["weakness"]  # it does not claim the engine is right or wrong here
    assert "not filled" in text["strength"] and "nothing is stated as a rate" in text["strength"]


def test_the_limits_name_what_was_asked_for(v):
    text = " ".join(v["limits"])
    for phrase in ("landslides, debris flows", "HAND", "constant water depth", "no ground truth at the peak", "high-water marks",
                   "41 hours", "2.5% of its basin", "rainfall source ends in 2020"):
        assert phrase in text, phrase
