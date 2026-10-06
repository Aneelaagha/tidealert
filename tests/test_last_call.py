"""Last call (app.services.last_call, GET /map/last-call) against the local database, read-only. Zone-level, from the isolation
engine's stored evidence; the lead time is set by the caller and never measured here."""
import re
from datetime import datetime, timedelta, timezone

import pytest

from app.services import last_call as lc

BEFORE_PEAK = "2017-08-27T18:30:00Z"
PEAK = "2017-08-27T20:00:00Z"
LATER = "2017-08-28T20:00:00Z"
T0 = datetime(2017, 8, 27, 12, 0, tzinfo=timezone.utc)


def board(client, run, at, **lead):
    r = client.get("/map/last-call", params={"run_id": run["id"], "at": at, **lead})
    assert r.status_code == 200, r.text
    return r.json()


def mins(m):
    return timedelta(minutes=m)


# ---------------------------------------------------------------- the status rule, on small cases
def test_a_zone_counts_down_to_its_cutoff_minus_the_lead_then_passes_then_is_cut_off():
    ev = [(T0 + mins(100), True)]
    lead = mins(40)
    s = lc.zone_status(ev, T0, lead)
    assert (s["status"], s["last_call_at"], s["cutoff_at"], s["hindsight"]) == ("counting", T0 + mins(60), T0 + mins(100), True)
    assert lc.zone_status(ev, T0 + mins(59), lead)["status"] == "counting"
    assert lc.zone_status(ev, T0 + mins(60), lead)["status"] == "passed"  # the moment of last call
    assert lc.zone_status(ev, T0 + mins(99), lead)["status"] == "passed"
    s = lc.zone_status(ev, T0 + mins(100), lead)
    assert s["status"] == "cut_off" and s["hindsight"] is False and s["cutoff_at"] == T0 + mins(100)


def test_with_no_lead_set_last_call_is_the_cutoff_time():
    s = lc.zone_status([(T0 + mins(30), True)], T0, mins(0))
    assert s["last_call_at"] == s["cutoff_at"]


def test_a_reconnected_zone_is_reconnected_not_lost_and_a_later_cutoff_counts_down_again():
    ev = [(T0 + mins(10), True), (T0 + mins(20), True), (T0 + mins(50), False), (T0 + mins(200), True)]
    assert lc.zone_status(ev, T0 + mins(30), mins(0))["cutoff_at"] == T0 + mins(10)  # since the start of this run of cut-off rows
    assert lc.zone_status(ev, T0 + mins(60), mins(0))["status"] == "counting"  # reconnected, then cut off again at +200
    again = lc.zone_status(ev, T0 + mins(60), mins(30))
    assert again["cutoff_at"] == T0 + mins(200) and again["was_reconnected"] is True
    done = lc.zone_status(ev[:3], T0 + mins(60), mins(30))
    assert done["status"] == "reconnected" and done["last_call_at"] is None and done["hindsight"] is False


def test_a_zone_with_no_evidence_has_nothing_to_say():
    assert lc.zone_status([], T0, mins(10)) is None
    assert lc.zone_status([(T0 + mins(10), False)], T0, mins(10)) is None  # only a future reconnection: nothing known, no cut-off


def test_the_lead_is_validated():
    assert lc.check_lead(5, 10, 30) == 45
    for bad in ((-1, 0, 0), (0, 1441, 0), (0, 0, -5)):
        with pytest.raises(lc.LastCallError):
            lc.check_lead(*bad)


# ---------------------------------------------------------------- against the stored Harvey evidence
def test_before_the_peak_some_zones_are_counting_down_and_the_rest_are_already_cut_off(client, runs):
    b = board(client, runs["harvey"], BEFORE_PEAK, travel_min=60)
    c = b["counts"]
    assert c["counting"] > 0 and c["cut_off"] > 0 and sum(c.values()) == 152
    zone = next(z for z in b["zones"] if z["status"] == "counting")
    assert zone["hindsight"] is True
    cut = datetime.fromisoformat(zone["cutoff_at"])
    assert datetime.fromisoformat(zone["last_call_at"]) == cut - mins(60)
    assert zone["minutes_to_cutoff"] - zone["minutes_to_last_call"] == 60  # the arithmetic is the lead


def test_cutoff_times_are_the_engines_recorded_evidence(client, runs):
    """A zone's recorded cut-off equals the 'cut off since' the safety service reports once the time has come."""
    run = runs["harvey"]
    b = board(client, run, BEFORE_PEAK)
    counting = [z for z in b["zones"] if z["status"] == "counting"][:5]
    assert counting
    for z in counting:
        later = client.get("/map/supply-access", params={"run_id": run["id"], "at": z["cutoff_at"]}).json()["zones"][z["zone_id"]]
        assert later["zone_access"] == "isolated" and later["since"].startswith(z["cutoff_at"][:16])
        earlier = client.get("/map/supply-access", params={"run_id": run["id"], "at": (datetime.fromisoformat(z["cutoff_at"]) - mins(15)).isoformat()}).json()["zones"][z["zone_id"]]
        assert earlier["zone_access"] != "isolated"  # it was not cut off a step earlier


def test_the_counts_agree_with_supply_access_at_the_same_time(client, runs):
    run = runs["harvey"]
    for at in (BEFORE_PEAK, PEAK, LATER):
        c = board(client, run, at)["counts"]
        sa = client.get("/map/supply-access", params={"run_id": run["id"], "at": at}).json()["counts"]
        assert c["cut_off"] == sa["isolated"]["zones"], at
    assert board(client, run, LATER)["counts"]["reconnected"] == client.get("/map/supply-access", params={"run_id": run["id"], "at": LATER}).json()["counts"]["reconnected"]["zones"]


def test_at_the_peak_everything_flagged_is_cut_off_and_nothing_counts_down(client, runs):
    c = board(client, runs["harvey"], PEAK, travel_min=90)["counts"]
    assert c == {"counting": 0, "passed": 0, "cut_off": 152, "reconnected": 0}


def test_the_board_lists_the_soonest_last_call_first(client, runs):
    zs = [z for z in board(client, runs["harvey"], BEFORE_PEAK, travel_min=30)["zones"] if z["status"] == "counting"]
    soon = [z["minutes_to_last_call"] for z in zs]
    assert soon == sorted(soon)
    b = board(client, runs["harvey"], BEFORE_PEAK, travel_min=30)
    assert [z["status"] for z in b["zones"]] == sorted((z["status"] for z in b["zones"]), key=["counting", "passed", "cut_off", "reconnected"].index)


def test_a_lead_longer_than_the_wait_puts_a_zone_past_its_last_call(client, runs):
    b = board(client, runs["harvey"], BEFORE_PEAK, travel_min=120)  # the zones cut off in 75 minutes are already past a 120-minute lead
    assert b["counts"]["passed"] > 0 and b["counts"]["counting"] == 0
    passed = [z for z in b["zones"] if z["status"] == "passed"]
    assert all(z["minutes_to_last_call"] is None and z["minutes_to_cutoff"] > 0 for z in passed)


def test_the_mixed_run_shows_a_reconnected_zone_counting_down_again(client, runs):
    if "mixed" not in runs:
        pytest.skip("mixed run not in the local database")
    b = board(client, runs["mixed"], "2017-08-28T03:00:00Z")  # reconnected at 02:15, cut off again at 03:45
    again = [z for z in b["zones"] if z["status"] == "counting" and z["was_reconnected"]]
    assert again, "the mixed run's re-isolation zones should count down again after a reconnection"


# ---------------------------------------------------------------- honesty and refusals
def test_it_says_it_is_hindsight_zone_level_and_the_lead_is_not_measured(client, runs):
    b = board(client, runs["harvey"], BEFORE_PEAK, reply_min=10, decision_min=5, travel_min=30)
    assert b["lead"] == {"reply_minutes": 10, "decision_minutes": 5, "travel_minutes": 30, "total_minutes": 45, "note": b["lead"]["note"]}
    assert "not measured" in b["lead"]["note"]
    for phrase in ("hindsight", "forecast", "Per zone, not per household", "no dry road route"):
        assert phrase in b["label"]


def test_it_never_claims_a_recovery_or_that_every_channel_is_closed(client, runs):
    shown = str(board(client, runs["harvey"], BEFORE_PEAK, travel_min=30)) + lc.LABEL
    assert not re.search(r"recovery|any channel|cannot be reached by any|no longer be reached", shown, re.I)
    assert "never claims" not in shown


def test_a_run_the_engine_did_not_run_on_has_no_last_call_and_says_why(client, runs):
    for kind in ("listening", "silence"):
        b = board(client, runs[kind], "2026-09-10T17:00:00Z" if kind == "listening" else "2026-09-02T19:00:00Z")
        assert b["available"] is False and b["zones"] == [] and "Unknown stays unknown" in b["reason"]


def test_bad_leads_and_times_are_refused(client, runs):
    run = runs["harvey"]
    assert client.get("/map/last-call", params={"run_id": run["id"], "travel_min": -1}).status_code == 422
    assert client.get("/map/last-call", params={"run_id": run["id"], "reply_min": 99999}).status_code == 422
    assert client.get("/map/last-call", params={"run_id": run["id"], "at": "2001-01-01T00:00:00Z"}).status_code == 422
    assert client.get("/map/last-call", params={"run_id": "00000000-0000-0000-0000-000000000000"}).status_code == 404
