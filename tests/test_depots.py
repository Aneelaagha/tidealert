"""Depot access (app.services.depots / depot_reach, GET /map/depots and /map/depot-access) against the local database
and the stored files written by scripts/depot_access.py. Read-only. Feasibility only: no route, distance or time."""
import json
import uuid
from pathlib import Path

import pytest

PEAK = "2017-08-27T20:00:00Z"
BASE = "2017-08-26T12:00:00Z"
LATER = "2017-08-28T20:00:00Z"


@pytest.fixture(scope="module")
def depots(client, runs):
    r = client.get("/map/depots", params={"run_id": runs["harvey"]["id"]})
    assert r.status_code == 200, r.text
    return r.json()


def access(client, runs, depot, at, kind="harvey"):
    r = client.get("/map/depot-access", params={"run_id": runs[kind]["id"], "depot_id": depot["id"], "at": at})
    assert r.status_code == 200, r.text
    return r.json()


def isolated(client, runs, at):
    d = client.get("/map/supply-access", params={"run_id": runs["harvey"]["id"], "at": at}).json()
    return {z for z, v in d["zones"].items() if v["zone_access"] == "isolated"}


def test_the_candidate_depots_are_real_osm_fire_stations_with_their_ids_and_fetch_time(depots):
    assert depots["available"] and len(depots["depots"]) == 9  # three per basin
    for d in depots["depots"]:
        assert d["source"] == "OpenStreetMap (amenity=fire_station)" and d["osm"].split("/")[0] in ("node", "way")
        assert 0 <= d["snapped_to_road_m"] <= 150 and d["osm_fetched_at"].startswith("2026-")
        assert d["id"] == f"{d['site']}:{d['osm']}"
    assert {d["site"] for d in depots["depots"]} == {"08074500", "08076000", "08075770"}
    assert "nothing says they served as depots" in depots["does_not_show"]


def test_only_harvey_runs_have_depot_access(client, runs):
    for kind in ("listening", "silence"):
        d = client.get("/map/depots", params={"run_id": runs[kind]["id"]}).json()
        assert d["available"] is False and d["depots"] == [] and "Harvey" in d["reason"]
    if "mixed" in runs:
        assert client.get("/map/depots", params={"run_id": runs["mixed"]["id"]}).json()["available"] is True


def test_at_base_flow_every_evaluated_zone_is_reachable_from_every_depot(client, runs, depots):
    for d in depots["depots"]:
        a = access(client, runs, d, BASE)
        c = a["counts"]
        assert c["not_reachable"]["zones"] == 0 and c["only_if_unknown_roads_passable"]["zones"] == 0
        assert c["reachable"]["zones"] == len(a["zones"]) - c["not_evaluated"]["zones"] > 0
        assert a["depot"]["road_dry"] is True


def test_it_reduces_to_the_isolation_engine_where_the_depot_is_in_the_main_network(client, runs, depots):
    """Where a depot is in the main network, 'not reachable' from it equals the engine's isolated zones exactly: at the
    peak 49, 92 and 11 zones, the engine's confirmed-isolated counts. A depot that is itself cut off is not in the main
    network: it can reach the zones on its own island (so it need not contain the isolated set) and little else."""
    iso = isolated(client, runs, PEAK)
    exact = {}
    for d in depots["depots"]:
        a = access(client, runs, d, PEAK)
        nr = {z for z, s in a["zones"].items() if s == "not_reachable"}
        basin_iso = iso & set(a["zones"])
        if nr == basin_iso:
            exact[d["site"]] = exact.get(d["site"], 0) + 1
            assert len(nr) == {"08074500": 49, "08076000": 92, "08075770": 11}[d["site"]]
        else:
            assert len(nr) > 0.5 * len(a["zones"]), d["id"]  # only a depot that is itself cut off differs
    assert set(exact) == {"08074500", "08076000", "08075770"}  # in every basin, at least one depot is in the main network


def test_a_depot_whose_own_road_is_cut_off_reaches_almost_nothing_and_says_so(client, runs, depots):
    iso = isolated(client, runs, PEAK)
    stranded = []
    for d in depots["depots"]:
        a = access(client, runs, d, PEAK)
        nr = sum(1 for s in a["zones"].values() if s == "not_reachable")
        if nr > len({z for z in iso if z in a["zones"]}):
            stranded.append((d["id"], nr, len(a["zones"])))
    assert stranded  # the Hunting Bayou station that is itself cut off at the peak
    assert all(nr > 0.5 * total for _, nr, total in stranded)


def test_the_stored_files_record_zero_disagreement_with_the_engine(client, runs, depots):
    seen = set()
    for d in depots["depots"]:
        if d["site"] in seen:
            continue
        seen.add(d["site"])
        ag = access(client, runs, d, PEAK)["engine_agreement"]
        assert ag["mismatched"] == 0 and ag["depot_ticks_checked"] > 1000, d["site"]


def test_it_reads_the_latest_computed_step_on_or_before_the_time_and_never_a_later_one(client, runs, depots):
    d = depots["depots"][0]
    a = access(client, runs, d, "2017-08-27T20:10:00Z")
    assert a["tick_at"] == "2017-08-27T20:00:00+00:00" and a["at"].startswith("2017-08-27T20:10")


def test_the_answer_states_what_it_does_not_show_and_returns_no_route(client, runs, depots):
    a = access(client, runs, depots["depots"][0], LATER)
    assert "finds no route" in a["does_not_show"] and "no distance, time, vehicle" in a["does_not_show"]
    assert not {"route", "geometry", "distance", "path"} & set(a)
    assert set(a["zones"].values()) <= {"reachable", "only_if_unknown_roads_passable", "not_reachable", "not_evaluated"}


def test_unknown_depot_other_runs_and_bad_times_are_refused(client, runs, depots):
    d = depots["depots"][0]
    p = {"run_id": runs["harvey"]["id"], "depot_id": d["id"]}
    assert client.get("/map/depot-access", params={**p, "depot_id": "08074500:node/0"}).status_code == 404
    assert client.get("/map/depot-access", params={**p, "at": "2001-01-01T00:00:00Z"}).status_code == 422
    assert client.get("/map/depot-access", params={"run_id": runs["listening"]["id"], "depot_id": d["id"]}).status_code == 404
    assert client.get("/map/depot-access", params={"run_id": str(uuid.uuid4()), "depot_id": d["id"]}).status_code == 404


def test_the_depots_served_are_the_tracked_candidates_with_their_osm_ids(depots):
    tracked = json.loads((Path(__file__).resolve().parent.parent / "backend" / "app" / "depot_candidates.json").read_text())
    want = {f"{site}:{d['osm']}": (d["name"], e["osm_fetched_at"]) for site, e in tracked["sites"].items() for d in e["depots"]}
    got = {d["id"]: (d["name"], d["osm_fetched_at"]) for d in depots["depots"]}
    assert got == want and len(got) == 9
    assert "OpenStreetMap" in tracked["source"] and "EXAMPLE" in tracked["note"]
