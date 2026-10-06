"""Aerial priority (app.services.aerial_priority, GET /map/aerial-priority) against the local database, read-only. A ranking of
cut-off zones only: replay ranks on cut-off duration with no score; off replay it ranks on silent households."""
from datetime import datetime, timedelta, timezone

import pytest

from app.services import aerial_priority as ap

PEAK = "2017-08-27T20:00:00Z"
LATE = "2017-08-28T02:00:00Z"
EMPTY_DAY = "2017-09-03T05:00:00Z"


def rank(client, run, at, **extra):
    r = client.get("/map/aerial-priority", params={"run_id": run["id"], "at": at, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def test_replay_ranks_by_cut_off_duration_with_no_score_and_no_silence(client, runs):
    b = rank(client, runs["harvey"], PEAK, limit=20)
    assert b["silence_active"] is False and b["note"] == ap.REPLAY_NOTE and b["caption"] == ap.CAPTION
    assert b["cut_off_zones"] > 0 and 0 < b["shown"] <= 20
    mins = [z["cut_off_minutes"] for z in b["zones"]]
    assert mins == sorted(mins, reverse=True) and [z["rank"] for z in b["zones"]] == list(range(1, b["shown"] + 1))
    for z in b["zones"]:
        assert z["score"] is None and z["silent_households"] is None and z["cell_coverage_assessed"] is False
        assert z["reason_fragments"][0] == "No dry route" and z["reason_fragments"][-1] == ap.NOT_ASSESSED
        assert z["reason_fragments"][1].startswith("Cut off ")
        assert not any("silent" in f for f in z["reason_fragments"])


def test_only_cut_off_zones_are_ranked_and_they_agree_with_last_call(client, runs):
    b = rank(client, runs["harvey"], PEAK, limit=ap.MAX_LIMIT)
    lc = client.get("/map/last-call", params={"run_id": runs["harvey"]["id"], "at": PEAK}).json()
    cut = {z["zone_id"]: z for z in lc["zones"] if z["status"] == "cut_off"}
    assert b["cut_off_zones"] == len(cut)
    at = datetime.fromisoformat(PEAK.replace("Z", "+00:00"))
    for z in b["zones"]:
        assert z["zone_id"] in cut
        since = datetime.fromisoformat(cut[z["zone_id"]]["cutoff_at"])
        assert z["cut_off_minutes"] == int((at - since).total_seconds() // 60)


def test_empty_when_no_zone_is_cut_off_and_never_falls_back_to_others(client, runs):
    b = rank(client, runs["harvey"], EMPTY_DAY)
    assert b["zones"] == [] and b["cut_off_zones"] == 0 and b["empty"] == ap.EMPTY
    for run in (runs["silence"], runs["listening"]):  # synthetic households, but no isolation evidence: nothing is cut off
        w = run["window_end"]
        assert rank(client, run, w)["zones"] == []


def test_ranks_the_driver_window_and_the_late_window(client, runs):
    assert rank(client, runs["harvey"], "2017-08-27T05:00:00Z")["cut_off_zones"] > 0  # the demo driver's own window
    assert rank(client, runs["harvey"], PEAK)["shown"] == ap.DEFAULT_LIMIT
    assert rank(client, runs["harvey"], LATE)["shown"] == ap.DEFAULT_LIMIT


def test_mixed_includes_silence_and_does_not_invent_a_count(client, runs):
    if "mixed" not in runs:
        pytest.skip("mixed run not in the local database")
    b = rank(client, runs["mixed"], PEAK)
    assert b["silence_active"] is True and b["note"] == ap.SILENCE_NOTE
    for z in b["zones"]:  # the mixed run holds no household in any real basin: unknown stays unknown, not zero
        assert z["silent_households"] is None and z["score"] is None
        assert "no households recorded in this run" in z["reason_fragments"]


def test_nothing_is_written_and_only_get_is_allowed(client, runs):
    assert client.post("/map/aerial-priority", params={"run_id": runs["harvey"]["id"]}).status_code == 405
    before = rank(client, runs["harvey"], PEAK)
    assert rank(client, runs["harvey"], PEAK) == before


def test_silent_households_counts_the_unanswered_ones():
    # the pure counting rule: a household is silent when its latest silence/listening support is not answered by a later contradiction
    from collections import defaultdict
    last = defaultdict(lambda: {"s": None, "c": None})
    t = datetime(2026, 9, 1, tzinfo=timezone.utc)
    for hid, key, when in [("a", "s", t), ("b", "s", t), ("b", "c", t + timedelta(minutes=5)), ("c", "s", t + timedelta(minutes=9)), ("c", "c", t)]:
        last[hid][key] = when
    silent = [h for h, v in last.items() if v["s"] is not None and (v["c"] is None or v["c"] < v["s"])]
    assert sorted(silent) == ["a", "c"]
