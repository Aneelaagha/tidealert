"""The after-action report (app.services.after_action, GET /reports/after-action) against the local database,
read-only. Every number it states is checked against the endpoint the page already shows it from."""
import uuid

AT = "2017-08-28T20:00:00Z"


def report(client, run, at=AT):
    r = client.get("/reports/after-action", params={"run_id": run["id"], "at": at})
    assert r.status_code == 200, r.text
    return r.json()


def test_the_report_is_labelled_with_the_runs_mode_first(client, runs):
    h = report(client, runs["harvey"])
    assert h["run"]["mode"] == "replay" and h["run"]["event"] == "Hurricane Harvey"
    assert h["run"]["mode_label"].startswith("REPLAY") and "no responders" in h["run"]["mode_label"]
    assert h["markdown"].split("\n")[2].startswith("**REPLAY")
    s = client.get("/reports/after-action", params={"run_id": runs["silence"]["id"]}).json()
    assert s["run"]["mode_label"].startswith("SYNTHETIC") and "not a real event" in s["run"]["mode_label"]
    if "mixed" in runs:
        m = report(client, runs["mixed"])
        assert m["run"]["mode_label"].startswith("MIXED") and "SYNTHETIC responders" in m["run"]["mode_label"]
        assert "SCRIPTED SYNTHETIC actions, not real responders" in m["markdown"]


def test_the_counts_are_the_ones_the_page_shows(client, runs):
    run = runs["harvey"]
    r = report(client, run)
    cases = client.get("/cases", params={"run_id": run["id"], "at": AT}).json()["cases"]
    tasks = client.get("/tasks", params={"run_id": run["id"], "at": AT}).json()["tasks"]
    sa = client.get("/map/supply-access", params={"run_id": run["id"], "at": AT}).json()
    s = r["summary"]
    assert s["cases"] == len(cases) and s["flagged_zones"] == len({c["zone_id"] for c in cases})
    assert s["tasks"] == len(tasks) and sum(s["tasks_by_status"].values()) == len(tasks)
    assert s["zones_cut_off"] == sa["counts"]["isolated"] and s["zones_not_assessed"] == sa["counts"]["not_evaluated"]
    assert sum(s["cases_by_confidence"].values()) == len(cases)
    warnings = [w for c in cases for t in c["tasks"] for w in t["safety"]["warnings"]]
    assert r["warnings"]["total"] == len(warnings)


def test_the_timeline_matches_the_stored_times_and_is_in_order(client, runs):
    run = runs["harvey"]
    r = report(client, run)
    cases = client.get("/cases", params={"run_id": run["id"], "at": AT}).json()["cases"]
    opened = sorted(c["opened_at"] for c in cases)
    first = next(x for x in r["timeline"] if x["kind"] == "first_case")
    last = next(x for x in r["timeline"] if x["kind"] == "last_case")
    assert first["at"] == opened[0] and last["at"] == opened[-1]
    assert [x["at"] for x in r["timeline"]] == sorted(x["at"] for x in r["timeline"])
    assert any(x["kind"] == "peak" and x["at"] == "2017-08-27T20:00:00+00:00" for x in r["timeline"])  # peak <= as-of
    early = client.get("/reports/after-action", params={"run_id": run["id"], "at": "2017-08-27T10:00:00Z"}).json()
    assert not any(x["kind"] == "peak" for x in early["timeline"])  # the report does not know the future


def test_a_replay_records_no_actions_and_says_so(client, runs):
    r = report(client, runs["harvey"])
    assert r["actions"] == [] and r["summary"]["actions_taken"] == 0
    assert "No assignments or other actions were recorded." in r["markdown"]


def test_actions_are_the_non_engine_task_events(client, runs):
    if "mixed" not in runs:
        return
    run = runs["mixed"]
    r = report(client, run)
    tasks = client.get("/tasks", params={"run_id": run["id"], "at": AT}).json()["tasks"]
    human = [e for t in tasks for e in t["events"] if not e["actor"].startswith("engine")]
    assert len(r["actions"]) == len(human) == r["summary"]["actions_taken"] and human
    assert all(a["synthetic"] for a in r["actions"])  # every action on the mixed run is scripted


def test_the_caveats_are_the_runs_own_and_the_limits_are_stated(client, runs):
    r = report(client, runs["harvey"])
    assert r["caveats"] == runs["harvey"]["caveats"]
    for c in r["caveats"] + r["limits"]:
        assert c in r["markdown"]
    assert any("unvalidated" in x for x in r["limits"]) and any("nothing about what happened to people" in x for x in r["limits"])


def test_unknown_run_is_404_and_a_time_outside_the_window_is_422(client, runs):
    assert client.get("/reports/after-action", params={"run_id": str(uuid.uuid4())}).status_code == 404
    assert client.get("/reports/after-action", params={"run_id": runs["harvey"]["id"], "at": "2001-01-01T00:00:00Z"}).status_code == 422
