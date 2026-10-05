"""The mixed scenario (scripts/mixed_harvey_scenario.py): Harvey's real flood and isolation results with a synthetic
responder layer. These run against the mixed run itself, not a rolled-back unit test: the after-assignment warning
must fire on Harvey's real reconnect -> cut-off-again transition. Read-only, except the migration round trip, which
runs inside a transaction that is rolled back."""
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text

from app.database import SessionLocal, engine
from app.models import Case, Responder, Run, Task
from app.models.case_engine_contribution import CaseEngineContribution as C
from app.services import map_state

ROOT = Path(__file__).resolve().parent.parent
BEFORE_MIXED = "edb82fd12167"  # the revision before run_mode_mixed (b7e3f0a91c52); later migrations come off with it
MIXED_CAVEAT = ("Mixed scenario: Harvey's real recorded flood and isolation results, with synthetic responders and "
                "assignments layered on top. The responders, assignments and anything they cause are not real.")


@pytest.fixture()
def mixed(runs):
    if "mixed" not in runs:
        pytest.skip("mixed run not in the local database: run scripts/mixed_harvey_scenario.py")
    return runs["mixed"]


def assigned(client, run, at):
    """The run's assigned tasks at `at`, by the scripted role recorded in their assignment note."""
    names = {r["id"]: r["name"] for r in client.get("/responders", params={"run_id": run["id"]}).json()["responders"]}
    out = {}
    for t in client.get("/tasks", params={"run_id": run["id"], "at": at}).json()["tasks"]:
        if t["assigned_responder_id"]:
            note = next(e["note"] for e in t["events"] if e["note"].startswith("assigned to"))
            role = note.split("scripted (", 1)[1].split(")", 1)[0]
            out.setdefault(role, []).append({**t, "responder": names[t["assigned_responder_id"]]})
    return out


def codes(t):
    return [w["code"] for w in t["safety"]["warnings"]]


# ---------------------------------------------------------------- the real transition
def test_the_three_hunting_tasks_warn_from_the_real_cut_off_again(client, mixed):
    for at in ("2017-08-28T02:30:00Z", "2017-08-28T03:30:00Z"):  # assigned during the 1.5 h reconnection
        tasks = assigned(client, mixed, at)["re-isolation"]
        assert len(tasks) == 3
        assert all(t["safety"]["zone_access"] == "reconnected" and codes(t) == [] for t in tasks), at
    for at in ("2017-08-28T03:45:00Z", "2017-08-28T06:00:00Z"):  # cut off again, after the assignment
        tasks = assigned(client, mixed, at)["re-isolation"]
        assert all(t["safety"]["zone_access"] == "isolated" and codes(t) == ["isolated_after_assignment"] for t in tasks)
        assert all("after the responder was assigned (2017-08-28 02:30 UTC)" in t["safety"]["warnings"][0]["text"]
                   for t in tasks)


def test_control_assigned_into_an_already_cut_off_zone(client, mixed):
    (t,) = assigned(client, mixed, "2017-08-27T18:30:00Z")["control: already cut off"]
    assert codes(t) == ["zone_isolated"] and "assigned after that" in t["safety"]["warnings"][0]["text"]


def test_control_that_stays_reconnected_never_warns(client, mixed):
    (t,) = assigned(client, mixed, "2017-08-29T21:00:00Z")["control: stays reconnected"]
    assert t["safety"]["zone_access"] == "reconnected" and codes(t) == []
    later = assigned(client, mixed, mixed["window_end"])["control: stays reconnected"][0]
    assert later["safety"]["zone_access"] == "reconnected" and codes(later) == []


def test_assignments_went_through_the_real_actions(client, mixed):
    roles = assigned(client, mixed, mixed["window_end"])
    tasks = [t for ts in roles.values() for t in ts]
    assert sorted(r for r in roles) == ["control: already cut off", "control: stays reconnected", "re-isolation"]
    assert len(tasks) == 5
    for t in tasks:
        actors = {e["actor"] for e in t["events"] if not e["actor"].startswith("engine:")}
        assert actors == {"script:mixed-scenario (synthetic)"}
    names = {r["name"] for r in client.get("/responders", params={"run_id": mixed["id"]}).json()["responders"]}
    assert names == {f"Synthetic responder {i}" for i in range(1, 7)}


# ---------------------------------------------------------------- the flood layer is real and Harvey is untouched
def _engine_output(db, run_id, prefix):
    n = dict(db.execute(select(C.case_id, func.count()).group_by(C.case_id)).all())
    return sorted((c.source.removeprefix(prefix), str(c.zone_id), c.opened_at, c.confidence_word.value, n.get(c.id, 0))
                  for c in db.scalars(select(Case).where(Case.run_id == run_id)))


def test_mixed_engine_output_equals_harvey_case_for_case(runs, mixed):
    with SessionLocal() as db:
        harvey = _engine_output(db, runs["harvey"]["id"], "backtest:2017-08-25..2017-09-02")
        ours = _engine_output(db, mixed["id"], "mixed:2017-08-25..2017-09-02")
        statuses = dict(db.execute(select(Case.status, func.count()).where(Case.run_id == mixed["id"])
                                   .group_by(Case.status)).all())
    assert len(harvey) == 152 and ours == harvey
    # The only differences: the 5 scripted assignments moved their Cases to in progress.
    assert {s.value: n for s, n in statuses.items()} == {"open": 147, "in_progress": 5}


def test_harvey_is_untouched(client, runs):
    harvey = runs["harvey"]
    with SessionLocal() as db:
        tasks = db.scalar(select(func.count()).select_from(Task).join(Case, Task.case_id == Case.id)
                          .where(Case.run_id == harvey["id"]))
        responders = db.scalar(select(func.count()).select_from(Responder).where(Responder.run_id == harvey["id"]))
        sources = {s for (s,) in db.execute(select(Case.source).where(Case.run_id == harvey["id"]).distinct())}
        statuses = {s.value for (s,) in db.execute(select(Case.status).where(Case.run_id == harvey["id"]).distinct())}
    assert (tasks, responders) == (152, 0)
    assert all(s.startswith("backtest:") for s in sources) and statuses == {"open"}
    assert next(r for r in client.get("/runs").json()["runs"] if r["id"] == harvey["id"])["task_actions_blocked"]


# ---------------------------------------------------------------- labelling
def test_runs_label_the_mixed_run_everywhere(client, mixed):
    assert mixed["mode"] == "mixed"
    assert mixed["description"] == "Mixed scenario: Harvey's real flood + synthetic responders"
    assert mixed["caveats"][0] == MIXED_CAVEAT == map_state.CAVEATS[map_state.RunMode.mixed]
    assert map_state.CAVEATS[map_state.RunMode.replay] in mixed["caveats"]  # its flood layer is the replayed record
    assert mixed["task_actions_blocked"] is None
    assert "mixed" in client.get("/runs").json()["vocabulary"]["mode"]


def test_copilot_as_of_line_says_mixed(client, mixed, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    b = client.post("/copilot/ask", json={"run_id": mixed["id"], "intent": "open_cases",
                                          "at": "2017-08-28T06:00:00Z"}).json()
    assert b["answer"].startswith("As of 2017-08-28 06:00 UTC (MIXED run)")


# ---------------------------------------------------------------- the migration
def _alembic(connection) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.attributes["connection"] = connection
    return cfg


def _modes(connection) -> list[str]:
    # From the catalog: enum_range() would "use" a value added in this uncommitted transaction, which Postgres refuses.
    return connection.execute(text("SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                                   "WHERE t.typname = 'run_mode' ORDER BY e.enumsortorder")).scalars().all()


def test_migration_round_trip_in_a_rolled_back_transaction():
    with engine.connect() as connection:
        outer = connection.begin()
        try:
            # Downgrade refuses while mixed runs exist; re-mark them inside this transaction to exercise the trip.
            connection.execute(text("UPDATE runs SET mode = 'scenario' WHERE mode::text = 'mixed'"))
            command.downgrade(_alembic(connection), BEFORE_MIXED)
            assert _modes(connection) == ["replay", "scenario", "live"]
            command.upgrade(_alembic(connection), "head")
            assert _modes(connection) == ["replay", "scenario", "live", "mixed"]
        finally:
            outer.rollback()
    with engine.connect() as connection:
        assert _modes(connection) == ["replay", "scenario", "live", "mixed"]  # nothing leaked out


def test_downgrade_refuses_while_mixed_runs_exist(mixed):
    with engine.connect() as connection:
        outer = connection.begin()
        try:
            with pytest.raises(RuntimeError, match="mode 'mixed'"):
                command.downgrade(_alembic(connection), BEFORE_MIXED)
        finally:
            outer.rollback()
    with SessionLocal() as db:
        assert db.scalar(select(Run.mode).where(Run.id == mixed["id"])).value == "mixed"
