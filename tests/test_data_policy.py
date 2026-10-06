"""The API's data policy (app.services.data_policy), enforced on every route: no route returns a per-person
field, and only the reviewed routes can write. New routes fail here until they are reviewed: a write route until
it is added to WRITE_ROUTES, a read route until it is added to the response scan below.

Read-only against the local database (needs the runs in tests/conftest.py)."""
import pytest
from fastapi.routing import APIRoute

from app.main import app
from app.services.data_policy import PERSONAL_FIELDS, WRITE_ROUTES, flatten_routes, model_fields

READ_METHODS = {"GET", "HEAD", "OPTIONS"}


def api_routes() -> list[APIRoute]:
    return list(flatten_routes(app.routes))


def test_the_route_inventory_is_complete():
    """Guards the guard: every check below iterates api_routes(), so an empty or partial list would pass them all."""
    found = {(m, r.path) for r in api_routes() for m in r.methods}
    for known in [("GET", "/runs"), ("GET", "/map/zones"), ("GET", "/zones/{zone_id}"), ("POST", "/copilot/ask"),
                  ("POST", "/tasks/{task_id}/assign")]:
        assert known in found, f"{known} missing: api_routes() is not seeing every route"


def keys_in(value, path="") -> set[str]:
    """Every key in a JSON value, with where it was found (for the failure message)."""
    found: set[str] = set()
    if isinstance(value, dict):
        for k, v in value.items():
            found.add(k)
            found |= keys_in(v, f"{path}.{k}")
    elif isinstance(value, list):
        for v in value:
            found |= keys_in(v, path)
    return found


def test_only_reviewed_routes_can_write():
    writes = {(m, r.path) for r in api_routes() for m in r.methods - READ_METHODS}
    assert writes == set(WRITE_ROUTES), (
        f"unreviewed write routes: {sorted(writes - WRITE_ROUTES)}; listed but gone: {sorted(WRITE_ROUTES - writes)}")


def test_no_route_can_set_a_zone_or_touch_households():
    for r in api_routes():
        assert not r.path.startswith("/households"), f"household route {r.path} is back"
        if r.path.startswith("/zones"):
            assert r.methods <= READ_METHODS, f"{r.path} writes zones: zones are written only by the engines"
        body = set().union(*(model_fields(p.field_info.annotation) for p in r.dependant.body_params))
        assert "risk_level" not in body, f"{sorted(r.methods)} {r.path} accepts a risk_level"


def test_no_response_model_declares_a_personal_field():
    for r in api_routes():
        leaked = model_fields(r.response_model) & PERSONAL_FIELDS
        assert not leaked, f"{r.path} declares {sorted(leaked)}"


# How the scan calls each read route. A GET route missing from here fails test_every_read_route_is_scanned.
def _calls(client, runs):
    out = []
    for kind in ("harvey", "listening", "silence"):
        run_id = runs[kind]["id"]
        zones = client.get("/map/zones", params={"run_id": run_id}).json()
        zone_id = zones["features"][0]["properties"]["zone_id"]
        tasks = client.get("/tasks", params={"run_id": run_id}).json()["tasks"]
        out += [("/map/zones", {"run_id": run_id}), ("/map/freshness", {"run_id": run_id}), ("/map/supply-access", {"run_id": run_id}), ("/map/depots", {"run_id": run_id}), ("/needs", {"run_id": run_id}), ("/reports/after-action", {"run_id": run_id}),
                ("/cases", {"run_id": run_id}), ("/tasks", {"run_id": run_id}),
                ("/responders", {"run_id": run_id}), (f"/zones/{zone_id}", {})]
        if tasks:
            out.append((f"/tasks/{tasks[0]['id']}", {}))
    return out + [("/gauges/current", {}), ("/validation/harvey", {}), ("/validation/helene", {}), ("/runs", {}), ("/responders", {}), ("/zones/", {"limit": 100}), ("/copilot/status", {}),
                  ("/health", {}), ("/data-practices", {})]


SCANNED = {"/runs", "/map/zones", "/map/freshness", "/map/supply-access", "/needs", "/reports/after-action", "/validation/harvey", "/validation/helene", "/gauges/current", "/cases", "/tasks", "/tasks/{task_id}", "/responders",
           "/zones/", "/zones/{zone_id}", "/copilot/status", "/health", "/data-practices", "/", "/ui/"}  # "/" and "/ui/" only redirect or serve the page


def test_every_read_route_is_scanned():
    reads = {r.path for r in api_routes() if r.methods & {"GET"}}
    assert reads <= SCANNED, f"read routes not in the response scan: {sorted(reads - SCANNED)}"


def test_no_response_returns_a_personal_field(client, runs):
    for path, params in _calls(client, runs):
        r = client.get(path, params=params)
        assert r.status_code == 200, (path, r.status_code)
        leaked = keys_in(r.json()) & PERSONAL_FIELDS
        assert not leaked, f"GET {path} returned {sorted(leaked)}"


@pytest.mark.parametrize("intent", ["briefing", "zone_cases", "zone_status"])
def test_copilot_answers_return_no_personal_field(client, runs, monkeypatch, intent):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    listening = runs["listening"]["id"]
    block_a = next(f["properties"] for f in client.get("/map/zones", params={"run_id": listening}).json()["features"]
                   if f["properties"]["name"].endswith("block A"))
    r = client.post("/copilot/ask", json={"run_id": listening, "intent": intent, "zone_id": block_a["zone_id"]})
    assert r.status_code == 200
    assert not keys_in(r.json()) & PERSONAL_FIELDS


def test_the_removed_routes_are_gone(client):
    assert client.get("/households/").status_code == 404
    zone_id = client.get("/zones/", params={"limit": 1}).json()[0]["id"]
    assert client.patch(f"/zones/{zone_id}", json={"risk_level": "safe"}).status_code == 405
    assert client.post("/zones/", json={}).status_code == 405
    assert client.delete(f"/zones/{zone_id}").status_code == 405
