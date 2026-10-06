"""Current gauge readings (app.services.gauge_readings, GET /gauges/current). The fetch is injected, so these tests do
not depend on the network; one opt-in test at the end asks USGS for real and skips when it cannot be reached."""
from datetime import datetime, timedelta, timezone

import pytest
import requests

from app.database import SessionLocal
from app.services import gauge_readings as g

NOW = datetime(2026, 10, 6, 6, 0, tzinfo=timezone.utc)


class Resp:
    def __init__(self, props=None, status=200):
        self.props, self.status = props, status

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(f"{self.status} error")

    def json(self):
        return {"features": [] if self.props is None else [{"properties": self.props}]}


def reading(minutes_ago, value="8.16", unit="ft"):
    return {"time": (NOW - timedelta(minutes=minutes_ago)).isoformat(), "value": value, "unit_of_measure": unit,
            "approval_status": "Provisional", "qualifier": None}


def fake(ages: dict, fail=()):
    """ages: site -> minutes since the newest reading; sites in `fail` raise a connection error."""
    def get(url, params, timeout):
        site = params["monitoring_location_id"].removeprefix("USGS-")
        if site in fail:
            raise requests.ConnectionError("connection refused")
        assert url == g.OGC and params["sortby"] == "-time" and params["limit"] == 1 and timeout == g.TIMEOUT_SECONDS
        return Resp(reading(ages[site], "42.5", "ft" if params["parameter_code"] == "00065" else "ft^3/s"))
    return get


def run(get, now=NOW):
    with SessionLocal() as db:
        return g.current(db, now=now, get=get, use_cache=False)


def test_a_reading_is_fresh_until_the_stored_stale_after_limit_then_stale():
    ages = {s: 10 for s in g.SITES} | {"08074500": 59, "08076000": 61}
    body = run(fake(ages))
    by = {x["site"]: x for x in body["gauges"]}
    assert by["08074500"]["status"] == "fresh" and by["08076000"]["status"] == "stale"  # the limit stored for these sources is 3600 s
    assert by["08075770"]["age_seconds"] == 600 and by["08074500"]["stale_after_seconds"] == 3600
    assert body["available"] is True and body["fetched_at"] == NOW.isoformat()


def test_values_are_the_fetched_ones_with_their_observation_time_and_approval():
    body = run(fake({s: 5 for s in g.SITES}))
    r = body["gauges"][0]["readings"]["gage height"]
    assert (r["value"], r["unit"], r["approval"]) == (42.5, "ft", "Provisional")
    assert r["observed_at"] == (NOW - timedelta(minutes=5)).isoformat()
    assert body["gauges"][0]["readings"]["discharge"]["unit"] == "ft^3/s"


def test_it_says_it_is_not_a_live_run():
    assert "Not a live run" in run(fake({s: 5 for s in g.SITES}))["label"]


def test_when_usgs_cannot_be_reached_it_says_so_and_shows_no_value():
    body = run(fake({}, fail=set(g.SITES)))
    assert body["available"] is False and "could not be reached" in body["reason"] and "connection refused" in body["reason"]
    for gauge in body["gauges"]:
        assert gauge["status"] == "unavailable" and gauge["newest_observed_at"] is None and gauge["age_seconds"] is None
        assert all("value" not in r and "error" in r for r in gauge["readings"].values())  # nothing invented or carried over


def test_one_failing_gauge_does_not_hide_the_others_or_borrow_their_values():
    body = run(fake({s: 5 for s in g.SITES}, fail={"03451500"}))
    by = {x["site"]: x for x in body["gauges"]}
    assert body["available"] is True and by["03451500"]["status"] == "unavailable" and by["08076000"]["status"] == "fresh"
    assert "value" not in by["03451500"]["readings"]["gage height"]


def test_an_empty_answer_is_unavailable_not_zero():
    body = run(lambda url, params, timeout: Resp(None))
    assert body["available"] is False and all(x["status"] == "unavailable" for x in body["gauges"])
    assert "USGS returned no reading" in body["reason"]


def test_every_project_gauge_is_asked_for_both_parameters_and_each_has_a_name():
    asked = []

    def get(url, params, timeout):
        asked.append((params["monitoring_location_id"], params["parameter_code"]))
        return Resp(reading(5))
    body = run(get)
    assert sorted(asked) == sorted((f"USGS-{s}", c) for s in g.SITES for c in g.PARAMETERS)
    assert all(x["name"] for x in body["gauges"])


def test_the_route_answers_unavailable_not_an_error_when_the_network_is_down(client, monkeypatch):
    def down(*a, **k):
        raise requests.ConnectionError("network unreachable")
    monkeypatch.setattr(g.requests, "get", down)
    g._cache.update(at=0.0, body=None)
    r = client.get("/gauges/current")
    try:
        assert r.status_code == 200 and r.json()["available"] is False and "network unreachable" in r.json()["reason"]
    finally:
        g._cache.update(at=0.0, body=None)


def test_real_usgs_readings_parse_when_the_network_is_available():
    with SessionLocal() as db:
        body = g.current(db, use_cache=False)
    if not body["available"]:
        pytest.skip("USGS not reachable from here: " + str(body["reason"]))
    some = next(x for x in body["gauges"] if x["status"] != "unavailable")
    h = some["readings"]["gage height"]
    assert isinstance(h["value"], float) and h["unit"] == "ft" and datetime.fromisoformat(h["observed_at"]).tzinfo is not None
