"""Helene (Asheville, Sep 2024): the facts the validation write-up rests on, from the local pipeline reports
(backend/app/data/usgs-0345*/backtest.json). Skips when the Helene pipeline hasn't been run here."""
import json
import os

import pytest

DATA = os.path.join(os.path.dirname(__file__), "..", "backend", "app", "data")


def report(site):
    path = os.path.join(DATA, f"usgs-{site}", "backtest.json")
    if not os.path.exists(path):
        pytest.skip(f"run scripts/run_isolation_pipeline.py {site} --start 2024-09-25T04:00Z --end 2024-10-01T04:00Z")
    with open(path) as f:
        r = json.load(f)
    if not r["window_utc"][0].startswith("2024-09-25"):
        pytest.skip("the local report is not for the Helene window")
    return r


def test_the_swannanoa_gap_stays_missing():
    prov = report("03451000")["stage_provenance"]
    assert prov["missing"] == 150 and prov["rating"] == 28 and prov["observed"] == 399


def test_the_french_broad_record_is_complete():
    prov = report("03451500")["stage_provenance"]
    assert prov.get("missing", 0) == 0 and prov.get("rating", 0) == 0 and prov["observed"] == 577


@pytest.mark.parametrize("site", ["03451000", "03451500"])
def test_both_gauges_run_on_hand_at_lower_confidence(site):
    driver = report(site)["river_driver"]
    assert driver["confidence"] == "LOWER CONFIDENCE" and driver["method"].startswith("HAND")


def test_the_swannanoa_says_why_its_library_was_refused():
    assert "BLTN7) does not resolve stage" in report("03451000")["river_driver"]["caveat"]


@pytest.mark.parametrize("site", ["03451000", "03451500"])
def test_no_zone_is_confirmed_isolated(site):
    assert report(site)["zone_status"].get("isolated", {"zones": 0})["zones"] == 0
