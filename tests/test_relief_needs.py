"""Relief needs and pledges (app.services.relief_needs, /relief/needs): test pledges, no payments. API tests run inside a
transaction that is rolled back; the race test builds and removes its own temporary run on separate real connections."""
import json
import re
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import SessionLocal, engine, get_db
from app.main import app
from app.models import Case, NeedPledge, Run, Zone, ZoneNeed
from app.models.zone_need import ItemType, ReliefStatus
from app.services import relief_needs as rn
from app.services.relief_needs import ReliefError
from app.services.task_actions import TaskActionError
from test_task_action_races import race, temporary_world

ROOT = Path(__file__).resolve().parent.parent
MIXED = "mixed:harvey-synthetic-responders:2017-08-25..2017-09-02"
HARVEY = "backtest:2017-08-25..2017-09-02"
LATER = "2017-08-28T20:00:00Z"  # isolated, possibly isolated, reconnected, dry and not-assessed zones all exist then
PEAK = "2017-08-27T20:00:00Z"


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


def zone_in(client, run, state, at=LATER):
    d = client.get("/map/supply-access", params={"run_id": str(run.id), "at": at}).json()
    return next(z for z, v in d["zones"].items() if v["zone_access"] == state)


def zones_in(client, run, state, at=LATER, n=2):
    d = client.get("/map/supply-access", params={"run_id": str(run.id), "at": at}).json()
    return [z for z, v in d["zones"].items() if v["zone_access"] == state][:n]


def post(client, run, zone, item="water", qty=100, by="coordinator", at=LATER):
    return client.post("/relief/needs", json={"run_id": str(run.id), "zone_id": zone, "item_type": item, "quantity_needed": qty,
                                              "created_by": by, "at": at})


def pledge(client, need_id, qty, at=LATER):
    return client.post(f"/relief/needs/{need_id}/pledges", json={"quantity": qty, "at": at})


# ---------------------------------------------------------------- the schema refuses nonsense
def _insert(db, run_id, zone_id, **kw):
    row = dict(run_id=run_id, zone_id=zone_id, item_type=ItemType.water, quantity_needed=10, quantity_pledged=0,
               status=ReliefStatus.open, created_by="t", is_synthetic=False) | kw
    db.add(ZoneNeed(**row))
    db.flush()


@pytest.mark.parametrize("bad", [dict(quantity_needed=0), dict(quantity_needed=-5), dict(quantity_pledged=-1),
                                 dict(quantity_needed=10, quantity_pledged=11), dict(item_type=ItemType.boat),
                                 dict(item_type=ItemType.other), dict(status=ReliefStatus.filled, quantity_pledged=3)])
def test_the_database_refuses_a_need_that_breaks_a_constraint(tx, bad):
    _, db = tx
    run = run_named(db, MIXED)
    zone = db.scalar(select(Zone.id).where(Zone.region.in_(["USGS-08074500 basin"])).limit(1))
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            _insert(db, run.id, zone, **bad)


def test_a_pledge_cannot_be_zero_or_negative_and_has_no_identity_columns(tx):
    _, db = tx
    run = run_named(db, MIXED)
    zone = db.scalar(select(Zone.id).where(Zone.region.in_(["USGS-08074500 basin"])).limit(1))
    _insert(db, run.id, zone)
    need = db.scalar(select(ZoneNeed).where(ZoneNeed.run_id == run.id).order_by(ZoneNeed.created_at.desc()))
    for q in (0, -1):
        with pytest.raises(IntegrityError):
            with db.begin_nested():
                db.add(NeedPledge(need_id=need.id, quantity=q))
                db.flush()
    assert {c.name for c in NeedPledge.__table__.columns} == {"id", "need_id", "quantity", "created_at"}


def _alembic(connection) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.attributes["connection"] = connection
    return cfg


def test_the_migration_round_trips_in_a_rolled_back_transaction_and_refuses_to_drop_rows():
    with engine.connect() as connection:
        outer = connection.begin()
        try:
            connection.execute(text("DELETE FROM zone_needs"))
            command.downgrade(_alembic(connection), "a28b563698ed")
            cols = connection.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'zone_needs'")).scalars().all()
            assert "quantity_fulfilled" in cols and "quantity_pledged" not in cols
            assert connection.execute(text("SELECT to_regclass('need_pledges')")).scalar() is None
            command.upgrade(_alembic(connection), "head")
            cols = connection.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'zone_needs'")).scalars().all()
            assert {"quantity_pledged", "run_id", "is_synthetic", "created_by"} <= set(cols) and "quantity_fulfilled" not in cols
        finally:
            outer.rollback()
    with engine.connect() as connection:  # nothing leaked
        assert connection.execute(text("SELECT to_regclass('need_pledges')")).scalar() is not None


# ---------------------------------------------------------------- where it works
def test_replays_refuse_needs_and_pledges_in_plain_words(tx):
    client, db = tx
    harvey = run_named(db, HARVEY)
    zone = zone_in(client, harvey, "isolated")
    r = post(client, harvey, zone)
    assert r.status_code == 422 and "off for replays" in r.json()["detail"] and "invent a relief history" in r.json()["detail"]
    assert db.scalar(select(ZoneNeed).where(ZoneNeed.run_id == harvey.id)) is None
    # a need that somehow exists on a replay still cannot be pledged against
    _insert(db, harvey.id, db.get(Zone, uuid.UUID(zone)).id)
    nid = db.scalar(select(ZoneNeed.id).where(ZoneNeed.run_id == harvey.id))
    p = pledge(client, nid, 1)
    assert p.status_code == 422 and "off for replays" in p.json()["detail"]
    b = client.get("/relief/needs", params={"run_id": str(harvey.id), "at": LATER}).json()
    assert b["writable"] is False and b["blocked_reason"] == r.json()["detail"] and b["label"] == "Test pledges. No payment is processed."


def test_the_mixed_run_posts_a_need_pledges_and_the_bar_numbers_come_from_the_server(tx):
    client, db = tx
    run = run_named(db, MIXED)
    zone = zone_in(client, run, "isolated")
    r = post(client, run, zone, "food", 100)
    assert r.status_code == 201, r.text
    need = r.json()
    assert (need["quantity_needed"], need["quantity_pledged"], need["quantity_open"], need["percent"], need["status"]) == (100, 0, 100, 0.0, "open")
    assert need["item_label"] == "Food rations" and need["unit"] == "rations" and need["access"]["label"] == "Cut off"
    p = pledge(client, need["id"], 30)
    assert p.status_code == 201 and p.json()["quantity_pledged"] == 30 and p.json()["percent"] == 30.0 and p.json()["status"] == "partial"
    assert db.scalar(select(NeedPledge.quantity).where(NeedPledge.need_id == uuid.UUID(need["id"]))) == 30
    assert client.post(f"/relief/needs/{need['id']}/close", json={}).json()["status"] == "closed"
    assert pledge(client, need["id"], 1).status_code == 409  # closed: no more


def test_a_need_must_be_goods_positive_posted_by_someone_and_in_the_runs_view(tx):
    client, db = tx
    run = run_named(db, MIXED)
    zone = zone_in(client, run, "isolated")
    before = db.scalar(select(func.count()).select_from(ZoneNeed).where(ZoneNeed.run_id == run.id))
    assert post(client, run, zone, "boat").status_code == 422 and post(client, run, zone, "money").status_code == 422
    assert post(client, run, zone, qty=0).status_code == 422 and post(client, run, zone, qty=rn.MAX_QUANTITY + 1).status_code == 422
    assert post(client, run, zone, by="  ").status_code == 422
    assert post(client, run, str(uuid.uuid4())).status_code == 404
    assert db.scalar(select(func.count()).select_from(ZoneNeed).where(ZoneNeed.run_id == run.id)) == before  # none of them wrote anything


# ---------------------------------------------------------------- pledge semantics
def test_an_over_pledge_is_a_409_that_states_the_open_quantity_and_changes_nothing(tx):
    client, db = tx
    run = run_named(db, MIXED)
    need = post(client, run, zone_in(client, run, "isolated"), "water", 50).json()
    assert pledge(client, need["id"], 20).status_code == 201
    r = pledge(client, need["id"], 31)
    assert r.status_code == 409 and "only 30 litres are still open" in r.json()["detail"]
    after = db.get(ZoneNeed, uuid.UUID(need["id"]))
    db.refresh(after)
    assert after.quantity_pledged == 20 and after.status == ReliefStatus.partial
    assert db.scalar(select(NeedPledge.quantity).where(NeedPledge.need_id == after.id, NeedPledge.quantity == 31)) is None


def test_an_exact_fill_sets_filled_and_the_next_pledge_is_a_409(tx):
    client, db = tx
    run = run_named(db, MIXED)
    need = post(client, run, zone_in(client, run, "isolated"), "blankets", 10).json()
    r = pledge(client, need["id"], 10)
    assert r.status_code == 201 and r.json()["status"] == "filled" and r.json()["percent"] == 100.0 and r.json()["quantity_open"] == 0
    nxt = pledge(client, need["id"], 1)
    assert nxt.status_code == 409 and "filled" in nxt.json()["detail"]


def test_pledges_must_be_whole_positive_numbers(tx):
    client, db = tx
    run = run_named(db, MIXED)
    need = post(client, run, zone_in(client, run, "isolated")).json()
    for q in (0, -3):
        assert pledge(client, need["id"], q).status_code == 422
    assert client.post(f"/relief/needs/{need['id']}/pledges", json={"quantity": 1.5}).status_code == 422


# ---------------------------------------------------------------- concurrency
def test_threads_racing_for_the_last_unit_get_exactly_one_pledge():
    """Each thread opens its connection before the barrier, so a cold pool can't serialise them; without the row lock,
    several would read the same open quantity and each would be told it succeeded (the pledges would then sum past needed)."""
    with temporary_world(cases=1, responders=0, follow_up=False) as w:
        with SessionLocal() as db:
            zone_id = db.get(Case, w["cases"][0]).zone_id
            need = rn.post_need(db, db.get(Run, w["run"]), zone_id, "water", 1, "race test")
            need_id = need.id
            db.commit()

        def go(i, db):
            try:
                rn.pledge(db, need_id, 1)
            except ReliefError as exc:  # race() reports task-action errors by their HTTP code
                raise TaskActionError(exc.status_code, exc.detail)
        results = race(8, go)
        assert results.count("ok") == 1 and results.count(409) == 7, results
        with SessionLocal() as db:
            n = db.get(ZoneNeed, need_id)
            assert n.quantity_pledged == 1 == n.quantity_needed and n.status == ReliefStatus.filled
            assert sum(db.scalars(select(NeedPledge.quantity).where(NeedPledge.need_id == need_id))) == n.quantity_pledged


def test_many_small_pledges_race_without_ever_exceeding_needed():
    with temporary_world(cases=1, responders=0, follow_up=False) as w:
        with SessionLocal() as db:
            zone_id = db.get(Case, w["cases"][0]).zone_id
            need_id = rn.post_need(db, db.get(Run, w["run"]), zone_id, "food", 5, "race test").id
            db.commit()

        def go(i, db):
            try:
                rn.pledge(db, need_id, 1)
            except ReliefError as exc:
                raise TaskActionError(exc.status_code, exc.detail)
        results = race(12, go)
        assert results.count("ok") == 5 and results.count(409) == 7, results
        with SessionLocal() as db:
            n = db.get(ZoneNeed, need_id)
            assert n.quantity_pledged == 5 and n.status == ReliefStatus.filled


# ---------------------------------------------------------------- ordering
def test_needs_are_ranked_cut_off_then_may_be_then_not_assessed_then_reconnected_then_dry_route_then_largest_open(tx):
    client, db = tx
    run = run_named(db, MIXED)
    states = ["reachable", "reconnected", "not_evaluated", "possibly_isolated", "isolated"]  # posted worst-first on purpose
    for s in states:
        assert post(client, run, zone_in(client, run, s), "water", 10).status_code == 201
    big, small = zones_in(client, run, "isolated", n=3)[1:3]
    assert post(client, run, big, "food", 500).status_code == 201 and post(client, run, small, "blankets", 20).status_code == 201
    # the demo seed (three synthetic needs) may be on the board; the ranking is checked on the needs this test posted
    needs = [n for n in client.get("/relief/needs", params={"run_id": str(run.id), "at": LATER}).json()["needs"] if not n["is_synthetic"]]
    order = [n["access"]["state"] for n in needs]
    assert order == ["isolated"] * 3 + ["possibly_isolated", "not_evaluated", "reconnected", "reachable"], order
    iso = [n for n in needs if n["access"]["state"] == "isolated"]
    assert [n["quantity_open"] for n in iso] == sorted((n["quantity_open"] for n in iso), reverse=True)  # largest open first
    assert order.index("not_evaluated") < order.index("reachable")  # not assessed is never ranked below a dry zone


def test_a_filled_need_sorts_after_open_ones_in_its_group(tx):
    client, db = tx
    run = run_named(db, MIXED)
    a, b = zones_in(client, run, "isolated")
    filled = post(client, run, a, "water", 10).json()
    pledge(client, filled["id"], 10)
    open_ = post(client, run, b, "water", 1).json()
    ids = [n["id"] for n in client.get("/relief/needs", params={"run_id": str(run.id), "at": LATER}).json()["needs"]]
    assert ids.index(open_["id"]) < ids.index(filled["id"])


# ---------------------------------------------------------------- the seed
def test_the_seed_posts_three_synthetic_needs_on_cut_off_zones_by_the_documented_rule_and_is_idempotent(tx):
    client, db = tx
    run = run_named(db, MIXED)
    first = rn.seed_mixed(db, run)
    ids = lambda ns: [(str(n.zone_id), n.item_type.value, n.quantity_needed) for n in ns]  # noqa: E731
    assert len(first) == 3 and [n.item_type.value for n in first] == ["water", "food", "medical"]
    assert all(n.is_synthetic and n.created_by == rn.SEED_BY and n.quantity_pledged == 0 for n in first)
    peak = client.get("/map/supply-access", params={"run_id": str(run.id), "at": PEAK}).json()["zones"]
    assert all(peak[str(n.zone_id)]["zone_access"] == "isolated" for n in first)  # cut off at the demo time
    pops = [db.get(Zone, n.zone_id).population_count for n in first]
    assert pops == sorted(pops, reverse=True) and [n.quantity_needed for n in first] == pops  # largest population first; 1 unit per resident
    again = rn.seed_mixed(db, run)
    synthetic = select(func.count()).select_from(ZoneNeed).where(ZoneNeed.run_id == run.id, ZoneNeed.is_synthetic.is_(True))
    assert ids(again) == ids(first) and db.scalar(synthetic) == 3


def test_the_seed_replaces_its_own_needs_and_leaves_a_coordinators_alone(tx):
    client, db = tx
    run = run_named(db, MIXED)
    mine = post(client, run, zone_in(client, run, "reachable"), "water", 7).json()
    rn.seed_mixed(db, run)
    rn.seed_mixed(db, run)
    assert db.get(ZoneNeed, uuid.UUID(mine["id"])) is not None
    assert len(list(db.scalars(select(ZoneNeed).where(ZoneNeed.run_id == run.id, ZoneNeed.is_synthetic.is_(True))))) == 3


def test_the_seed_only_applies_to_the_mixed_run(tx):
    _, db = tx
    with pytest.raises(ReliefError):
        rn.seed_mixed(db, run_named(db, HARVEY))


# ---------------------------------------------------------------- honesty
def test_nothing_the_api_says_calls_a_pledge_delivered_or_received_and_no_identity_is_returned(tx):
    client, db = tx
    run = run_named(db, MIXED)
    need = post(client, run, zone_in(client, run, "isolated"), "medical", 10).json()
    shown = json.dumps([client.get("/relief/needs", params={"run_id": str(run.id), "at": LATER}).json(), pledge(client, need["id"], 4).json()])
    assert not re.search(r"deliver|receiv|fulfil", shown, re.I), shown[:200]
    assert not {"donor", "name", "email", "phone", "ip", "session"} & set(pledge(client, need["id"], 1).json())
    src = (ROOT / "backend" / "app" / "services" / "relief_needs.py").read_text()
    code = re.sub(r'""".*?"""', "", src, flags=re.S)  # the docstrings say "never delivered"; the code may not use the words
    assert not re.search(r"deliver|receiv|fulfil", code, re.I)
