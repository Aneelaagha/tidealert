"""The operator-entered needs board (app.services.needs, /needs). The API tests run inside a transaction that is
rolled back, so the local database is left as it was; the race test builds and removes its own temporary run.
Needs the Harvey replay and the mixed run for the Harvey cases (tests that need the mixed run skip without it)."""
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal, engine, get_db
from app.main import app
from app.models import Case, NeedEvent, Run, Zone
from app.models.need_event import NeedEventKind
from app.models.zone_need import ItemType
from app.services import needs
from app.services.needs import NeedError
from app.services.task_actions import TaskActionError
from test_task_action_races import START, race, temporary_world

HARVEY = "backtest:2017-08-25..2017-09-02"
MIXED = "mixed:harvey-synthetic-responders:2017-08-25..2017-09-02"
PEAK = "2017-08-27T18:30:00Z"
EARLY, LATER = "2017-08-28T08:00:00Z", "2017-08-28T10:00:00Z"


@pytest.fixture()
def tx():
    connection = engine.connect()
    outer = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    app.dependency_overrides[get_db] = lambda: session
    try:
        yield TestClient(app), session
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.close()
        outer.rollback()
        connection.close()


def run_named(db, name):
    run = db.scalar(select(Run).where(Run.name == name))
    if run is None:
        pytest.skip(f"run {name} not in the local database")
    return run


def a_zone(client, run, access, at=PEAK):
    d = client.get("/map/supply-access", params={"run_id": str(run.id), "at": at}).json()
    return next(z for z, v in d["zones"].items() if v["zone_access"] == access)


def enter(client, run, zone, **kw):
    body = {"run_id": str(run.id), "zone_id": zone, "item_type": "water", "event": "requested", "quantity": 10,
            "actor": "tester", "at": PEAK} | kw
    return client.post("/needs", json=body)


# ---------------------------------------------------------------- where it may be used
def test_the_harvey_replay_refuses_entries_and_says_why(tx):
    client, db = tx
    run = run_named(db, HARVEY)
    zone = a_zone(client, run, "isolated")
    r = enter(client, run, zone)
    assert r.status_code == 422 and "replay" in r.json()["detail"]
    assert db.scalar(select(NeedEvent).where(NeedEvent.run_id == run.id)) is None  # nothing was written
    d = client.get("/needs", params={"run_id": str(run.id)}).json()
    assert d["writable"] is False and d["blocked_reason"] == r.json()["detail"]  # the page shows the server's words


def test_the_mixed_run_accepts_entries_and_the_replay_never_shows_them(tx):
    client, db = tx
    mixed, harvey = run_named(db, MIXED), run_named(db, HARVEY)
    zone = a_zone(client, mixed, "isolated")  # the replay and the mixed run share zones
    r = enter(client, mixed, zone, quantity=40)
    assert r.status_code == 201, r.text
    assert r.json()["items"] == [{"item_type": "water", "requested": 40, "fulfilled": 0, "withdrawn": 0, "remaining": 40,
                                    "pledged": 0, "unpledged": 40}]
    assert "Not measured" in r.json()["label"]
    assert zone in client.get("/needs", params={"run_id": str(mixed.id), "at": PEAK}).json()["zones"]
    assert client.get("/needs", params={"run_id": str(harvey.id), "at": PEAK}).json()["zones"] == {}


# ---------------------------------------------------------------- the board, in time
def test_a_past_time_reads_only_what_had_been_entered_by_then(tx):
    client, db = tx
    run = run_named(db, MIXED)
    zone = a_zone(client, run, "isolated")
    assert enter(client, run, zone, quantity=50, at=EARLY).status_code == 201
    assert enter(client, run, zone, event="fulfilled", quantity=20, at=LATER).status_code == 201
    before = client.get("/needs", params={"run_id": str(run.id), "at": "2017-08-28T09:00:00Z"}).json()
    after = client.get("/needs", params={"run_id": str(run.id), "at": "2017-08-28T11:00:00Z"}).json()
    assert before["zones"][zone]["items"][0]["remaining"] == 50 and len(before["zones"][zone]["events"]) == 1
    assert after["zones"][zone]["items"][0]["remaining"] == 30 and len(after["zones"][zone]["events"]) == 2
    assert client.get("/needs", params={"run_id": str(run.id), "at": "2017-08-28T07:00:00Z"}).json()["zones"] == {}


def test_a_need_in_a_cut_off_zone_is_counted_as_one(tx):
    client, db = tx
    run = run_named(db, MIXED)
    cut, reach = a_zone(client, run, "isolated"), a_zone(client, run, "reachable")
    enter(client, run, cut, quantity=5)
    enter(client, run, reach, item_type="food", quantity=7)
    d = client.get("/needs", params={"run_id": str(run.id), "at": PEAK}).json()
    assert d["zones"][cut]["zone_access"] == "isolated" and d["zones"][reach]["zone_access"] == "reachable"
    s = d["summary"]
    assert s["zones_with_open_needs"] == 2 and s["open_in_cut_off_zones"] == 1 and s["cut_off_zone_ids"] == [cut]
    assert s["by_item"] == {"water": {"zones": 1, "remaining": 5, "pledged": 0, "unpledged": 5},
                          "food": {"zones": 1, "remaining": 7, "pledged": 0, "unpledged": 7}}


def test_a_closed_need_is_no_longer_open_or_flagged(tx):
    client, db = tx
    run = run_named(db, MIXED)
    zone = a_zone(client, run, "isolated")
    enter(client, run, zone, quantity=5, at=EARLY)
    enter(client, run, zone, event="withdrawn", quantity=5, at=LATER)
    d = client.get("/needs", params={"run_id": str(run.id), "at": "2017-08-28T11:00:00Z"}).json()
    assert d["zones"][zone]["open"] == 0 and d["zones"][zone]["zone_access"] is None
    assert d["summary"]["zones_with_open_needs"] == 0 and d["summary"]["by_item"] == {}


# ---------------------------------------------------------------- the rules
def test_entries_are_checked(tx):
    client, db = tx
    run = run_named(db, MIXED)
    zone = a_zone(client, run, "isolated")
    assert enter(client, run, zone, actor="  ").status_code == 422  # who is entering
    for q in (0, -3, needs.MAX_QUANTITY + 1):
        assert enter(client, run, zone, quantity=q).status_code == 422
    assert enter(client, run, zone, note="x" * (needs.MAX_NOTE + 1)).status_code == 422
    assert enter(client, run, zone, at="2001-01-01T00:00:00Z").status_code == 422  # outside the window
    assert enter(client, run, str(uuid.uuid4())).status_code == 404
    assert enter(client, run, zone, item_type="gold").status_code == 422
    assert db.scalar(select(NeedEvent).where(NeedEvent.run_id == run.id)) is None  # none of them wrote anything


def test_cannot_fulfil_or_withdraw_more_than_is_open_nor_go_back_in_time(tx):
    client, db = tx
    run = run_named(db, MIXED)
    zone = a_zone(client, run, "isolated")
    assert enter(client, run, zone, quantity=10, at=LATER).status_code == 201
    for event in ("fulfilled", "withdrawn"):
        r = enter(client, run, zone, event=event, quantity=11, at=LATER)
        assert r.status_code == 409 and "only 10" in r.json()["detail"], r.text
    r = enter(client, run, zone, event="fulfilled", quantity=1, at=EARLY)  # before the item's latest entry
    assert r.status_code == 422 and "before" in r.json()["detail"]
    assert enter(client, run, zone, item_type="food", event="fulfilled", quantity=1, at=LATER).status_code == 409  # none requested


def test_a_zone_outside_the_runs_view_is_refused(tx):
    client, db = tx
    run = run_named(db, MIXED)
    stray = db.scalar(select(Zone.id).where(Zone.region.like("synthetic:%")))
    if stray is None:
        pytest.skip("no synthetic zone in the local database")
    r = enter(client, run, str(stray))
    assert r.status_code == 422 and "not part of the run" in r.json()["detail"]


# ---------------------------------------------------------------- concurrency
def test_concurrent_fulfilments_cannot_spend_the_same_quantity_twice():
    with temporary_world(cases=1, responders=0, follow_up=False) as w:
        with SessionLocal() as db:
            zone_id = db.get(Case, w["cases"][0]).zone_id
            needs.record(db, db.get(Run, w["run"]), zone_id, ItemType.water, NeedEventKind.requested, 3, "race",
                         at=START)
            db.commit()

        def fulfil(i, db):
            try:
                needs.record(db, db.get(Run, w["run"]), zone_id, ItemType.water, NeedEventKind.fulfilled, 1, "race",
                             at=START + timedelta(hours=1))
            except NeedError as exc:  # race() reports task-action errors by their HTTP code
                raise TaskActionError(exc.status_code, exc.detail)
        results = race(6, fulfil)
        assert results.count("ok") == 3 and results.count(409) == 3, results  # 3 open: exactly 3 can be fulfilled
        with SessionLocal() as db:
            events = list(db.scalars(select(NeedEvent).where(NeedEvent.run_id == w["run"])))
            assert sum(e.quantity for e in events if e.event == NeedEventKind.fulfilled) == 3
