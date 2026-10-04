"""Copilot (template mode) against the local database. Read-only except one rolled-back test.
Needs the Harvey replay and the synthetic scenarios (see tests/conftest.py)."""
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import engine, get_db
from app.main import app
from app.models import Household
from app.models.household import AgeBracket
from app.services import copilot

PEAK = "2017-08-27T18:30:00Z"


@pytest.fixture(autouse=True)
def no_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def ask(client, **body):
    r = client.post("/copilot/ask", json=body)
    return r.status_code, r.json()


def test_without_a_key_the_copilot_uses_templates(client):
    s = client.get("/copilot/status").json()
    assert s["mode"] == "template" and "ANTHROPIC_API_KEY is not set" in s["reason"]
    assert set(s["intents"]) == set(copilot.INTENTS)
    assert s["needs"] == {"zone_status": "zone_id", "zone_cases": "zone_id", "briefing": "zone_id",
                          "explain_confidence": "case_id"}  # open_cases needs no selection


def test_zone_status_states_exactly_what_the_map_holds(client, runs):
    harvey = runs["harvey"]["id"]
    zones = [f["properties"] for f in client.get("/map/zones", params={"run_id": harvey, "at": PEAK}).json()["features"]]
    with_case = [z for z in zones if z["case_count"]][:25]
    assert with_case
    for z in with_case:
        code, b = ask(client, run_id=harvey, intent="zone_status", zone_id=z["zone_id"], at=PEAK)
        assert code == 200
        risk = re.search(r"Risk level: (\w+)", b["answer"]).group(1)
        word = re.search(r"strongest confidence word (\w+)", b["answer"]).group(1)
        assert (risk, word) == (z["risk_level"], z["confidence_word"])
        assert "Data confidence: not assessed." in b["answer"]  # null is stated, not filled
        assert b["answer"].startswith("As of 2017-08-27 18:30 UTC (REPLAY run)")


def test_gaps_are_stated_not_guessed(client, runs):
    harvey = runs["harvey"]["id"]
    zones = [f["properties"] for f in client.get("/map/zones", params={"run_id": harvey, "at": PEAK}).json()["features"]]
    empty = next(z for z in zones if not z["case_count"])
    code, b = ask(client, run_id=harvey, question="what's the status of this zone?", zone_id=empty["zone_id"], at=PEAK)
    assert code == 200 and b["intent"] == "zone_status"
    assert "Cases: none as of this time." in b["answer"] and "Case" in b["unknowns"]
    assert "Risk level: unknown (not assessed by any engine)." in b["answer"]


def test_out_of_scope_questions_get_the_fixed_reply(client, runs):
    code, b = ask(client, run_id=runs["harvey"]["id"], question="will it rain in Houston tomorrow?")
    assert code == 200 and b["in_scope"] is False and b["answer"] == copilot.OUT_OF_SCOPE


def test_explain_confidence_gives_the_rule(client, runs):
    harvey = runs["harvey"]["id"]
    case = client.get("/cases", params={"run_id": harvey}).json()["cases"][0]
    code, b = ask(client, run_id=harvey, question="why is this stale?", case_id=case["id"])
    assert code == 200 and b["intent"] == "explain_confidence"
    assert "reads stale_verify" in b["answer"] and "the most recent evidence contradicts the Case" in b["answer"]
    listening = runs["listening"]["id"]
    block = next(c for c in client.get("/cases", params={"run_id": listening}).json()["cases"]
                 if c["household_id"] is None)
    code, b = ask(client, run_id=listening, intent="explain_confidence", case_id=block["id"])
    assert "reads corroborated" in b["answer"] and "fresh support from 2 independent sources" in b["answer"]


def test_inputs_are_checked(client, runs):
    harvey = runs["harvey"]["id"]
    assert ask(client, run_id=harvey, intent="briefing")[0] == 422  # needs a zone
    assert ask(client, run_id=harvey, intent="explain_confidence")[0] == 422  # needs a Case
    zone = "00000000-0000-0000-0000-000000000000"
    assert ask(client, run_id=harvey, intent="zone_status", zone_id=zone)[0] == 404
    real_zone = client.get("/map/zones", params={"run_id": harvey}).json()["features"][0]["properties"]["zone_id"]
    assert ask(client, run_id=harvey, intent="zone_status", zone_id=real_zone, at="2016-01-01T00:00:00Z")[0] == 422


def test_briefing_is_a_labelled_draft_and_reports_household_data(client, runs):
    listening = runs["listening"]["id"]
    block_a = next(f["properties"] for f in client.get("/map/zones", params={"run_id": listening}).json()["features"]
                   if f["properties"]["name"].endswith("block A"))
    code, b = ask(client, run_id=listening, intent="briefing", zone_id=block_a["zone_id"])
    assert code == 200 and b["answer"].startswith("DRAFT RESPONDER BRIEFING")
    assert b["household_data"]["households"] > 0 and b["household_data"]["real"] == 0
    assert b["household_data"]["may_send_to_external_model"] is True  # synthetic only


def test_a_real_household_blocks_external_use(runs):
    """A household not marked synthetic (the default) makes every result touching it unsendable."""
    connection = engine.connect()
    outer = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    app.dependency_overrides[get_db] = lambda: session
    try:
        client = TestClient(app)
        listening = runs["listening"]["id"]
        block_a = next(f["properties"] for f in client.get("/map/zones", params={"run_id": listening}).json()["features"]
                       if f["properties"]["name"].endswith("block A"))
        session.add(Household(zone_id=block_a["zone_id"], latitude=0.0105, longitude=0.0105,
                              age_bracket=AgeBracket.age_18_64, primary_language="en"))  # is_synthetic not set
        session.commit()
        code, b = ask(client, run_id=listening, intent="briefing", zone_id=block_a["zone_id"])
        assert code == 200 and b["household_data"]["real"] == 1
        assert b["household_data"]["may_send_to_external_model"] is False
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.close()
        outer.rollback()
        connection.close()
