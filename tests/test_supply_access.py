"""Supply access (app.services.supply_access, GET /map/supply-access) against the local database, read-only.
It adds no measurement: each zone's state must equal the zone access responder safety already reports."""
import uuid

from app.services import supply_access

PEAK = "2017-08-27T18:30:00Z"
BEFORE = "2017-08-26T12:00:00Z"
LATER = "2017-08-28T20:00:00Z"


def get(client, run, at=None):
    r = client.get("/map/supply-access", params={"run_id": run["id"]} | ({"at": at} if at else {}))
    assert r.status_code == 200, r.text
    return r.json()


def test_every_zone_of_the_run_has_exactly_one_state(client, runs):
    d = get(client, runs["harvey"], PEAK)
    zones = client.get("/map/zones", params={"run_id": runs["harvey"]["id"], "at": PEAK}).json()["features"]
    assert set(d["zones"]) == {f["properties"]["zone_id"] for f in zones}
    assert sum(c["zones"] for c in d["counts"].values()) == len(zones)
    assert all(z["zone_access"] in supply_access.STATES for z in d["zones"].values())
    pop = {f["properties"]["zone_id"]: f["properties"]["population"] or 0 for f in zones}
    for state, c in d["counts"].items():
        assert c["population"] == sum(pop[z] for z, v in d["zones"].items() if v["zone_access"] == state)


def test_harvey_before_the_flood_nothing_is_cut_off_and_the_rest_is_stated(client, runs):
    c = get(client, runs["harvey"], BEFORE)["counts"]
    assert c["isolated"]["zones"] == c["possibly_isolated"]["zones"] == c["reconnected"]["zones"] == 0
    assert c["reachable"]["zones"] > 0 and c["not_evaluated"]["zones"] > 0  # zones the engine could not evaluate stay so


def test_harvey_at_the_peak_has_cut_off_zones_and_they_reconnect_later(client, runs):
    peak = get(client, runs["harvey"], PEAK)["counts"]
    later = get(client, runs["harvey"], LATER)["counts"]
    assert peak["isolated"]["zones"] > 0 and peak["reconnected"]["zones"] == 0
    assert later["reconnected"]["zones"] > 0 and later["isolated"]["zones"] < peak["isolated"]["zones"]


def test_state_agrees_with_each_tasks_own_zone_access(client, runs):
    run = runs["harvey"]
    d = get(client, run, LATER)
    cases = client.get("/cases", params={"run_id": run["id"], "at": LATER}).json()["cases"]
    checked = 0
    for c in cases:
        for t in c["tasks"]:
            assert d["zones"][c["zone_id"]]["zone_access"] == t["safety"]["zone_access"], c["id"]
            checked += 1
    assert checked > 0


def test_a_scenario_without_the_engine_is_not_assessed_never_reachable(client, runs):
    for kind in ("listening", "silence"):
        d = get(client, runs[kind])
        assert {z["zone_access"] for z in d["zones"].values()} == {"not_evaluated"}
        assert d["counts"]["reachable"]["zones"] == 0
        assert d["reasons"][0] == supply_access.safety.NOT_RUN_REASON


def test_it_states_what_it_does_not_show_and_returns_no_route(client, runs):
    d = get(client, runs["harvey"], PEAK)
    assert "depot" in d["does_not_show"] and "no route-by-route flood state" in d["does_not_show"]
    assert not {"geometry", "route", "route_geometry"} & set(d)
    assert all(z["reason_id"] < len(d["reasons"]) for z in d["zones"].values())


def test_unknown_run_is_404_and_a_time_outside_the_window_is_422(client, runs):
    assert client.get("/map/supply-access", params={"run_id": str(uuid.uuid4())}).status_code == 404
    assert client.get("/map/supply-access", params={"run_id": runs["harvey"]["id"], "at": "2001-01-01T00:00:00Z"}
                      ).status_code == 422
