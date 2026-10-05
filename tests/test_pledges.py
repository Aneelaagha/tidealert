"""The donation portal (app.services.pledges, POST /pledges and /pledges/{id}/close). API tests run inside a
transaction that is rolled back; the race test builds and removes its own temporary run. Needs the Harvey replay and
the mixed run (tests that need the mixed run skip without it)."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal, engine, get_db
from app.main import app
from app.models import Case, NeedEvent, Pledge, Run
from app.models.need_event import NeedEventKind
from app.models.pledge import PledgeClose
from app.models.zone_need import ItemType
from app.services import needs, pledges
from app.services.needs import NeedError
from app.services.task_actions import TaskActionError
from test_needs import EARLY, HARVEY, LATER, MIXED, PEAK, a_zone, enter, run_named
from test_task_action_races import START, race, temporary_world


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


def offer(client, run, zone, **kw):
    body = {"run_id": str(run.id), "zone_id": zone, "item_type": "water", "quantity": 10, "donor": "Gulf Coast Aid",
            "at": LATER} | kw
    return client.post("/pledges", json=body)


def close(client, pledge_id, **kw):
    return client.post(f"/pledges/{pledge_id}/close", json={"kind": "received", "actor": "operator", "at": LATER} | kw)


def board(client, run, at=None):
    return client.get("/needs", params={"run_id": str(run.id), "at": at or "2017-08-28T12:00:00Z"}).json()


def mixed_zone_with_need(client, db, quantity=50):
    run = run_named(db, MIXED)
    zone = a_zone(client, run, "isolated")
    assert enter(client, run, zone, quantity=quantity, at=EARLY).status_code == 201
    return run, zone


# ---------------------------------------------------------------- where
def test_the_replay_refuses_offers_and_nothing_is_written(tx):
    client, db = tx
    run = run_named(db, HARVEY)
    zone = a_zone(client, run, "isolated")
    r = offer(client, run, zone)
    assert r.status_code == 422 and "replay" in r.json()["detail"]
    assert db.scalar(select(Pledge).where(Pledge.run_id == run.id)) is None


# ---------------------------------------------------------------- an offer answers an open need
def test_an_offer_is_spoken_for_but_does_not_close_the_need(tx):
    client, db = tx
    run, zone = mixed_zone_with_need(client, db, 50)
    r = offer(client, run, zone, quantity=30)
    assert r.status_code == 201, r.text
    assert "no money is taken" in r.json()["label"] and "no contact details" in r.json()["label"]
    z = board(client, run)["zones"][zone]
    assert z["items"][0]["remaining"] == 50 and z["items"][0]["pledged"] == 30 and z["items"][0]["unpledged"] == 20
    assert [(p["donor"], p["quantity"], p["status"]) for p in z["pledges"]] == [("Gulf Coast Aid", 30, "offered")]
    s = board(client, run)["summary"]["by_item"]["water"]
    assert (s["remaining"], s["pledged"], s["unpledged"]) == (50, 30, 20)


def test_cannot_offer_more_than_is_open_and_unpledged_or_for_no_need(tx):
    client, db = tx
    run, zone = mixed_zone_with_need(client, db, 50)
    assert offer(client, run, zone, quantity=30).status_code == 201
    r = offer(client, run, zone, quantity=21)
    assert r.status_code == 409 and "only 20" in r.json()["detail"], r.text
    r = offer(client, run, zone, item_type="food")  # nobody asked for food here
    assert r.status_code == 409 and "no open need" in r.json()["detail"]
    r = offer(client, run, zone, at=PEAK)  # before the need was entered
    assert r.status_code == 422 and "before" in r.json()["detail"]


def test_offers_are_checked(tx):
    client, db = tx
    run, zone = mixed_zone_with_need(client, db)
    assert offer(client, run, zone, donor="  ").status_code == 422
    assert offer(client, run, zone, donor="x" * (pledges.MAX_DONOR + 1)).status_code == 422
    for q in (0, -1, needs.MAX_QUANTITY + 1):
        assert offer(client, run, zone, quantity=q).status_code == 422
    assert offer(client, run, zone, item_type="gold").status_code == 422
    assert db.scalar(select(Pledge).where(Pledge.run_id == run.id)) is None  # none of them wrote anything


@pytest.mark.parametrize("text", ["me@example.com", "call 713-555-0142", "(713) 555 0142", "https://x.org/me", "www.me.org",
                                  "+1 713 555 0142"])
def test_contact_details_are_refused_in_the_donor_and_the_note(tx, text):
    client, db = tx
    run, zone = mixed_zone_with_need(client, db)
    for field in ("donor", "note"):
        r = offer(client, run, zone, **{field: text})
        assert r.status_code == 422 and "contact details" in r.json()["detail"], (field, text, r.text)
    assert db.scalar(select(Pledge).where(Pledge.run_id == run.id)) is None


def test_ordinary_names_and_small_numbers_pass(tx):
    client, db = tx
    run, zone = mixed_zone_with_need(client, db)
    assert offer(client, run, zone, donor="St. Mary's Church (Pasadena)", note="2 pallets, bottled, 24 per case").status_code == 201


# ---------------------------------------------------------------- closing an offer
def test_receiving_an_offer_fulfils_that_much_of_the_need(tx):
    client, db = tx
    run, zone = mixed_zone_with_need(client, db, 50)
    pid = offer(client, run, zone, quantity=30).json()["pledge_id"]
    r = close(client, pid, at="2017-08-28T11:00:00Z")
    assert r.status_code == 200, r.text
    z = board(client, run, "2017-08-28T12:00:00Z")["zones"][zone]
    item = z["items"][0]
    assert (item["fulfilled"], item["remaining"], item["pledged"], item["unpledged"]) == (30, 20, 0, 20)
    assert z["pledges"][0]["status"] == "received" and z["pledges"][0]["closed_by"] == "operator"
    assert any(e["event"] == "fulfilled" and e["quantity"] == 30 and "received from pledge by Gulf Coast Aid" in e["note"]
               for e in z["events"])


def test_withdrawing_an_offer_returns_it_to_the_unpledged_need(tx):
    client, db = tx
    run, zone = mixed_zone_with_need(client, db, 50)
    pid = offer(client, run, zone, quantity=30).json()["pledge_id"]
    assert close(client, pid, kind="withdrawn").status_code == 200
    item = board(client, run)["zones"][zone]["items"][0]
    assert (item["remaining"], item["fulfilled"], item["pledged"], item["unpledged"]) == (50, 0, 0, 50)


def test_a_pledge_closes_once_and_not_before_it_was_offered(tx):
    client, db = tx
    run, zone = mixed_zone_with_need(client, db)
    pid = offer(client, run, zone, at=LATER).json()["pledge_id"]
    assert close(client, pid, actor=" ").status_code == 422
    r = close(client, pid, at=EARLY)
    assert r.status_code == 422 and "before the pledge was offered" in r.json()["detail"]
    assert close(client, pid, at="2017-08-28T11:00:00Z").status_code == 200
    r = close(client, pid, at="2017-08-28T11:30:00Z", kind="withdrawn")
    assert r.status_code == 409 and "already closed as received" in r.json()["detail"]
    assert client.post("/pledges/00000000-0000-0000-0000-000000000000/close",
                       json={"kind": "received", "actor": "o"}).status_code == 404


def test_the_need_cannot_be_withdrawn_or_fulfilled_out_from_under_an_open_pledge(tx):
    client, db = tx
    run, zone = mixed_zone_with_need(client, db, 50)
    assert offer(client, run, zone, quantity=40).status_code == 201
    for event in ("withdrawn", "fulfilled"):
        r = enter(client, run, zone, event=event, quantity=11, at=LATER)
        assert r.status_code == 409 and "pledged" in r.json()["detail"], r.text
    assert enter(client, run, zone, event="withdrawn", quantity=10, at=LATER).status_code == 201  # only the unpledged part


# ---------------------------------------------------------------- the board, in time and in cut-off zones
def test_a_past_time_reads_the_offers_open_then(tx):
    client, db = tx
    run, zone = mixed_zone_with_need(client, db, 50)
    pid = offer(client, run, zone, quantity=30, at="2017-08-28T09:00:00Z").json()["pledge_id"]
    assert close(client, pid, at="2017-08-28T11:00:00Z").status_code == 200
    at = {t: board(client, run, t)["zones"][zone] for t in ("2017-08-28T08:30:00Z", "2017-08-28T10:00:00Z", "2017-08-28T12:00:00Z")}
    assert at["2017-08-28T08:30:00Z"]["pledges"] == []
    assert at["2017-08-28T10:00:00Z"]["pledges"][0]["status"] == "offered" and at["2017-08-28T10:00:00Z"]["items"][0]["pledged"] == 30
    assert at["2017-08-28T12:00:00Z"]["pledges"][0]["status"] == "received" and at["2017-08-28T12:00:00Z"]["items"][0]["pledged"] == 0


def test_offers_to_a_cut_off_zone_are_allowed_and_counted_as_such(tx):
    client, db = tx
    run = run_named(db, MIXED)
    cut, reach = a_zone(client, run, "isolated"), a_zone(client, run, "reachable")
    for z in (cut, reach):
        assert enter(client, run, z, quantity=20, at=EARLY).status_code == 201
        assert offer(client, run, z, quantity=5, at=EARLY).status_code == 201
    s = board(client, run, EARLY)["summary"]
    assert s["open_pledges"] == 2 and s["open_pledges_in_cut_off_zones"] == 1


def test_the_replay_never_shows_a_mixed_run_pledge(tx):
    client, db = tx
    run, zone = mixed_zone_with_need(client, db)
    offer(client, run, zone)
    assert board(client, run_named(db, HARVEY))["zones"] == {}


# ---------------------------------------------------------------- concurrency
def test_concurrent_offers_cannot_pledge_the_same_quantity_twice():
    with temporary_world(cases=1, responders=0, follow_up=False) as w:
        with SessionLocal() as db:
            zone_id = db.get(Case, w["cases"][0]).zone_id
            needs.record(db, db.get(Run, w["run"]), zone_id, ItemType.water, NeedEventKind.requested, 3, "race", at=START)
            db.commit()

        def make(i, db):
            try:
                pledges.offer(db, db.get(Run, w["run"]), zone_id, ItemType.water, 1, f"donor {i}",
                              at=START + timedelta(hours=1))
            except NeedError as exc:  # race() reports task-action errors by their HTTP code
                raise TaskActionError(exc.status_code, exc.detail)
        results = race(6, make)
        assert results.count("ok") == 3 and results.count(409) == 3, results  # 3 open: exactly 3 can be pledged
        with SessionLocal() as db:
            assert len(list(db.scalars(select(Pledge).where(Pledge.run_id == w["run"])))) == 3


def test_concurrent_closings_of_one_pledge_succeed_exactly_once():
    with temporary_world(cases=1, responders=0, follow_up=False) as w:
        with SessionLocal() as db:
            zone_id = db.get(Case, w["cases"][0]).zone_id
            run = db.get(Run, w["run"])
            needs.record(db, run, zone_id, ItemType.water, NeedEventKind.requested, 5, "race", at=START)
            pid = pledges.offer(db, run, zone_id, ItemType.water, 5, "donor", at=START + timedelta(hours=1)).id
            db.commit()

        def receive(i, db):
            try:
                pledges.close(db, pid, PledgeClose.received, "race", at=START + timedelta(hours=2))
            except NeedError as exc:
                raise TaskActionError(exc.status_code, exc.detail)
        results = race(5, receive)
        assert results.count("ok") == 1 and results.count(409) == 4, results
        with SessionLocal() as db:  # fulfilled once, not five times
            events = list(db.scalars(select(NeedEvent).where(NeedEvent.run_id == w["run"],
                                                             NeedEvent.event == NeedEventKind.fulfilled)))
            assert [e.quantity for e in events] == [5]
