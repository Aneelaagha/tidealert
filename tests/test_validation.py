"""The validation panel's numbers (app.services.validation, GET /validation/harvey), pinned to their sources the way
the data-practices panel is: each displayed number is read again here, independently, from the file and place the
response names, and checked against the tables written in docs/algorithms/isolation-engine.md."""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOC = (ROOT / "docs" / "algorithms" / "isolation-engine.md").read_text()
SITES = {"08074500": "White Oak", "08076000": "Greens", "08075770": "Hunting"}


@pytest.fixture(scope="module")
def v(client):
    r = client.get("/validation/harvey")
    assert r.status_code == 200, r.text
    return r.json()


def test_it_names_the_run_the_event_and_the_data_window(v):
    assert v["run"] == "backtest:2017-08-25..2017-09-02" and v["event"] == "Hurricane Harvey"
    assert v["data_window_utc"][0].startswith("2017-08-25") and v["data_window_utc"][1].startswith("2017-09-03")


def test_each_lead_time_is_the_stored_value_in_the_named_file(v):
    assert {g["site"] for g in v["lead"]["rows"]} == set(SITES)
    for g in v["lead"]["rows"]:
        stored = json.loads((ROOT / g["source"]["file"]).read_text())
        assert g["first_road_floods_min"] == round(stored["lead_minutes_vs_alarm"]["first road segment floods"])
        assert g["first_zone_isolated_min"] == round(stored["lead_minutes_vs_alarm"]["first zone isolated"])
        assert g["alarm_minor_at"] == stored["alarm_minor"] and g["flood_source"] == stored["river_driver"]["method"]


def test_lead_times_match_the_docs_table(v):
    rows = {g["site"]: g for g in v["lead"]["rows"]}
    assert f"**+{rows['08074500']['first_road_floods_min']} min**" in DOC and f"**+{rows['08076000']['first_road_floods_min']} min**" in DOC
    assert f"+{rows['08075770']['first_road_floods_min']} min (unverified)" in DOC or f"+{rows['08075770']['first_road_floods_min']} min" in DOC
    assert f"+{rows['08074500']['first_zone_isolated_min']} min" in DOC
    assert f"−{abs(rows['08076000']['first_zone_isolated_min'])} min" in DOC  # the docs use a true minus sign


def test_only_the_gauges_with_an_nws_map_are_called_verified(v):
    by = {g["site"]: g for g in v["lead"]["rows"]}
    assert by["08074500"]["verified"] and by["08076000"]["verified"] and not by["08075770"]["verified"]
    assert "fallback" in by["08075770"]["alarm_source"]  # Hunting's alarm is a percentile fallback, not an NWS threshold
    assert "HAND" in by["08075770"]["flood_source"] or by["08075770"]["confidence"].lower().startswith("lower")


def test_zone_counts_are_the_stored_ones_and_match_the_docs(v):
    for z in v["zones"]["rows"]:
        stored = json.loads((ROOT / z["source"]["file"]).read_text())["zone_status"]
        assert z["status"] == stored
    assert "49 zones / 1,156 people" in DOC and "92 / 5,087" in DOC and "11 / 393" in DOC
    by = {z["site"]: z["status"]["isolated"] for z in v["zones"]["rows"]}
    assert (by["08074500"]["zones"], by["08074500"]["people"]) == (49, 1156) and (by["08076000"]["zones"], by["08076000"]["people"]) == (92, 5087)


def test_hand_agreement_is_the_stored_median_and_minimum(v):
    for h in v["hand"]["rows"]:
        stored = json.loads((ROOT / h["source"]["file"]).read_text())["hand_vs_nws_iou"]
        assert h["median"] == round(stored["event_steps_median"], 2) and h["minimum"] == round(stored["event_steps_min"], 2)
    assert "median 0.64 (0.58" in DOC and "median 0.70 (0.27" in DOC


def test_nfip_numbers_are_the_executed_notebook_outputs_and_match_the_docs(v):
    nb = json.loads((ROOT / "notebooks" / "nfip_validation.ipynb").read_text())
    printed = "\n".join("".join("".join(o.get("text", [])) for o in c.get("outputs", [])) for c in nb["cells"])
    n = v["nfip"]
    assert (n["all"]["bgs"], n["all"]["heavy"]) == (444, 90) and (n["covered"]["bgs"], n["covered"]["heavy"]) == (27, 14)
    for part in ("all", "covered"):
        for row in n[part]["rows"]:
            # the notebook printed this row with these exact numbers
            line = next(l for l in printed.splitlines() if l.startswith(row["flag"]) and f"{row['recall_heavy']:.3f}" in l)
            assert f"{row['share_flagged_heavy']:.3f}" in line and f"{row['precision_lb_any_claim']:.3f}" in line and f"{row['flagged_bgs']}" in line
    by = {r["flag"]: r for r in n["all"]["rows"]}
    for flag, pct in (("isolation Case (any time)", "14.4%"), ("FEMA 100-yr floodplain (static)", "67.8%"), ("FEMA 100+500-yr floodplain (static)", "82.2%")):
        assert f"{by[flag]['recall_heavy']:.1%}" == pct and pct in DOC
    assert f"{n['all']['base_rate_any_claim']:.1%}" in DOC and n["executed_at"].startswith("2026-")  # when the notebook ran


def test_the_unflattering_result_is_on_the_headline_not_hidden(v):
    kinds = {h["kind"]: h["text"] for h in v["headline"]}
    assert "does not beat the static map" in kinds["weakness"] and "14.4%" in kinds["weakness"] and "67.8%" in kinds["weakness"]
    assert re.search(r"37 to 75 minutes", kinds["strength"])


def test_the_limits_are_stated_and_say_there_is_no_observed_isolation(v):
    text = " ".join(v["limits"])
    for phrase in ("no observed-isolation ground truth", "lower confidence", "undercount flooding", "too small", "not modelled"):
        assert phrase in text
