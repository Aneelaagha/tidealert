"""Map API against the real database (read-only). See tests/conftest.py for the runs it needs."""
from collections import Counter

HARVEY_PEAK = "2017-08-27T18:30:00Z"  # White Oak's peak; sweep-recorded words: 133 single_source (49 + 73 + 11)


def zones(client, run, at=None):
    params = {"run_id": run["id"]}
    if at:
        params["at"] = at
    r = client.get("/map/zones", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_runs_have_explicit_modes_and_sources(runs):
    h = runs["harvey"]
    assert h["mode"] == "replay"
    assert h["case_count"] == 152
    assert [s["name"] for s in h["sources"]] == [
        "USGS 08074500 continuous", "USGS 08075770 continuous", "USGS 08076000 continuous"]
    assert runs["listening"]["mode"] == "scenario"
    assert runs["silence"]["mode"] == "scenario"
    assert runs["silence"]["sources"] == []
    assert not [r for r in runs["all"] if r["mode"] == "live"]  # none exists yet
    assert all(r["caveats"] for r in runs["all"])


def test_vocabulary_comes_from_the_schema(runs):
    v = runs["vocabulary"]
    assert v["risk_level"][0] == "unknown" and "safe" in v["risk_level"]
    assert set(v["mode"]) == {"replay", "scenario", "live"}
    assert set(v["coverage_gap"]) >= {"isolation", "river_driver"}


def test_every_zone_is_returned_and_none_defaults_to_safe(client, runs):
    body = zones(client, runs["harvey"])
    props = [f["properties"] for f in body["features"]]
    assert len(props) == 6049  # all zones of the three basins, with or without a Case
    assert Counter(p["risk_level"] for p in props) == {"unknown": 6049}
    assert all(p["data_confidence"] is None for p in props)
    assert sum(p["case_count"] == 0 for p in props) > 5000
    assert all(f["geometry"]["type"] == "Polygon" for f in body["features"])


def test_harvey_read_back_matches_the_sweep(client, runs):
    words = Counter(f["properties"]["confidence_word"] for f in zones(client, runs["harvey"], HARVEY_PEAK)["features"])
    assert words["single_source"] == 133 and words["stale_verify"] == 0
    end = [f["properties"] for f in zones(client, runs["harvey"])["features"] if f["properties"]["case_count"]]
    assert {p["confidence_word"] for p in end} == {"stale_verify"}  # every block had reconnected
    assert all(p["engines"] == ["isolation"] for p in end)  # no households in Harvey zones


def test_nothing_from_the_future(client, runs):
    start = zones(client, runs["harvey"], runs["harvey"]["window_start"])
    assert sum(f["properties"]["case_count"] for f in start["features"]) == 0
    early = [f["properties"] for f in zones(client, runs["listening"], "2026-09-10T14:15:00Z")["features"]]
    block_a = next(p for p in early if p["name"].endswith("block A"))
    assert block_a["risk_level"] == "unknown" and "after this time" in block_a["risk_level_note"]
    late = [f["properties"] for f in zones(client, runs["listening"], "2026-09-10T17:00:00Z")["features"]]
    assert next(p for p in late if p["name"].endswith("block A"))["risk_level"] == "extreme"


def test_coverage_gaps_follow_their_time(client, runs):
    before = zones(client, runs["harvey"], runs["harvey"]["window_start"])
    after = zones(client, runs["harvey"])
    gap = lambda f: next((g for g in f["properties"]["coverage_gaps"] if g["kind"] == "isolation"), None)  # noqa: E731
    pairs = [(gap(b), gap(a)) for b, a in zip(before["features"], after["features"]) if gap(a)]
    timed = [(b, a) for b, a in pairs if a["time_bound"]]  # possibly isolated from a stage onward
    permanent = [(b, a) for b, a in pairs if not a["time_bound"]]  # isolation not evaluated for the block
    assert len(timed) == 4250 and all(not b["active"] and a["active"] for b, a in timed)
    assert len(permanent) == 33 and all(b["active"] and a["active"] for b, a in permanent)
    assert all(0 <= g["reason_id"] < len(after["gap_reasons"]) for _, g in pairs)


def test_at_must_lie_in_the_window_and_carry_a_timezone(client, runs):
    for at in ("2016-01-01T00:00:00Z", "2017-08-27T18:30:00"):
        r = client.get("/map/zones", params={"run_id": runs["harvey"]["id"], "at": at})
        assert r.status_code == 422


def test_freshness(client, runs):
    h = client.get("/map/freshness", params={"run_id": runs["harvey"]["id"], "at": HARVEY_PEAK}).json()
    assert {s["name"]: s["status"] for s in h["sources"]} == {
        "USGS 08074500 continuous": "fresh", "USGS 08075770 continuous": "fresh", "USGS 08076000 continuous": "fresh"}
    assert all(s["stale_after_seconds"] == 3600 for s in h["sources"])
    early = client.get("/map/freshness", params={"run_id": runs["listening"]["id"], "at": "2026-09-10T14:15:00Z"}).json()
    assert early["sources"][0]["status"] == "no_data"
    late = client.get("/map/freshness", params={"run_id": runs["listening"]["id"]}).json()
    assert late["sources"][0]["status"] == "event_driven"
    silence = client.get("/map/freshness", params={"run_id": runs["silence"]["id"]}).json()
    assert silence["sources"] == [] and "not tracked" in silence["note"]


def test_cases_as_of_a_time(client, runs):
    at = HARVEY_PEAK
    body = client.get("/cases", params={"run_id": runs["harvey"]["id"], "at": at}).json()
    assert len(body["cases"]) == 133
    for case in body["cases"]:
        assert case["opened_at"] <= "2017-08-27T18:30:00+00:00"
        assert all(c["first_observed_at"] <= "2017-08-27T18:30:00+00:00" for c in case["contributions"])
    one = body["cases"][0]
    only = client.get("/cases", params={"run_id": runs["harvey"]["id"], "zone_id": one["zone_id"], "at": at}).json()
    assert [c["id"] for c in only["cases"]] == [one["id"]]


def test_unknown_run_is_404(client):
    assert client.get("/map/zones", params={"run_id": "00000000-0000-0000-0000-000000000000"}).status_code == 404


def test_map_page_is_served(client):
    page = client.get("/ui/")
    assert page.status_code == 200 and "maplibre-gl" in page.text and "map.js" in page.text
    script = client.get("/ui/map.js")
    assert script.status_code == 200 and "/map/zones" in script.text
    assert "task-marker" in script.text and "task_anchor" in script.text  # task markers from the API's anchors
    assert client.get("/", follow_redirects=False).headers["location"] == "/ui/"
