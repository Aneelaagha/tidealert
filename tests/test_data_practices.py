"""GET /data-practices states facts computed from the code and the database, and every known-gap line is pinned
to its source here: a gap must be listed while its condition holds and disappear when it stops holding. A new gap
fails test_every_gap_is_pinned until it gets a pin below. Read-only against the local database."""
import os
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.security import HTTPBearer
from pydantic import BaseModel
from sqlalchemy import func, select

from app.database import SessionLocal
from app.main import app
from app.models import Household, Responder
from app.services import data_practices, isolation_engine, map_state
from app.services.data_policy import PERSONAL_FIELDS, RESPONSE_SCAN, flatten_routes

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def report(client):
    r = client.get("/data-practices")
    assert r.status_code == 200
    return r.json()


def gaps(body) -> dict:
    return {g["id"]: g for g in body["known_gaps"]}


def routes_of(mini: FastAPI):
    return list(flatten_routes(mini.routes))


# ---------------------------------------------------------------- the computed facts
def test_counts_come_from_the_database(report):
    with SessionLocal() as db:
        households = db.scalar(select(func.count()).select_from(Household))
        real = db.scalar(select(func.count()).select_from(Household).where(Household.is_synthetic.is_(False)))
        responders = db.scalar(select(func.count()).select_from(Responder))
        real_resp = db.scalar(select(func.count()).select_from(Responder).where(Responder.run_id.is_(None)))
    assert report["households"] == {"total": households, "real": real, "synthetic": households - real}
    assert report["responders"] == {"total": responders, "real": real_resp, "synthetic": responders - real_resp}


def test_stored_and_exposed_fields(report):
    assert report["household_fields_stored"] == [c.name for c in Household.__table__.columns]
    assert report["personal_fields"] == sorted(PERSONAL_FIELDS)
    assert report["personal_fields_exposed"] == []  # tests/test_data_policy.py checks the real responses too


def test_exposed_fields_are_computed_from_response_models():
    class Leaky(BaseModel):
        contact_phone: str
    mini = FastAPI()

    @mini.get("/leak", response_model=Leaky)
    def leak():
        return {}
    assert data_practices.exposed_personal_fields(routes_of(mini)) == ["contact_phone"]


def test_authentication_is_computed_from_the_routes(report):
    assert report["authentication"] is False
    mini, bearer = FastAPI(), HTTPBearer()

    def user(token=Depends(bearer)):
        return token

    @mini.get("/secured")
    def secured(u=Depends(user)):
        return {}
    assert data_practices.authentication(routes_of(mini)) is True


def test_copilot_facts_match_the_copilot(report, client):
    status = client.get("/copilot/status").json()
    assert {report["copilot"][k] for k in ("mode", "reason")} == {status["mode"], status["reason"]}
    assert report["response_scan"] == RESPONSE_SCAN


# ---------------------------------------------------------------- each gap pinned to its source
PINNED = {"consent", "authentication", "tiles", "retention", "case_status_history", "confidence", "rain_driver",
          "response_scan"}


def test_every_gap_is_pinned(report):
    listed = set(gaps(report))
    assert listed <= PINNED, f"gaps without a pin test: {sorted(listed - PINNED)}"
    for g in report["known_gaps"]:
        assert g["text"] and g["source"], g


def test_consent_gap_follows_the_households_table(report, monkeypatch):
    assert report["consent_collected"] is False
    assert not any("consent" in c.name for c in Household.__table__.columns)
    assert "consent" in gaps(report)
    monkeypatch.setattr(data_practices, "consent_collected", lambda: True)
    assert "consent" not in {g["id"] for g in data_practices.known_gaps(list(flatten_routes(app.routes)))}


def test_authentication_gap_follows_the_routes(report, monkeypatch):
    assert "authentication" in gaps(report)
    monkeypatch.setattr(data_practices, "authentication", lambda routes: True)
    assert "authentication" not in {g["id"] for g in data_practices.known_gaps([])}


def test_tiles_gap_names_the_host_the_page_really_loads(report):
    page = (ROOT / "frontend/src/components/ZoneMap.tsx").read_text()
    assert data_practices.TILE_HOST in page, "the basemap changed: update TILE_HOST and the tiles gap"
    assert data_practices.TILE_HOST in gaps(report)["tiles"]["text"]


def test_retention_gap_holds_while_no_retention_process_exists(report):
    mentions = [str(p.relative_to(ROOT)) for d in ("backend/app", "scripts") for p in (ROOT / d).rglob("*.py")
                if "retention" in p.read_text().lower() and p.name != "data_practices.py"]
    assert mentions == [], f"retention code appeared ({mentions}): review the retention gap"
    assert "retention" in gaps(report)


def test_case_status_history_gap_matches_the_docs_and_schema(report):
    assert "Case status has no history" in (ROOT / "docs/api/map.md").read_text()
    from app.database import Base
    assert not [t for t in Base.metadata.tables if "case_status" in t], "a Case status history exists: drop the gap"
    assert "case_status_history" in gaps(report)


def test_confidence_gap_is_the_maps_own_caveat(report):
    assert gaps(report)["confidence"]["text"] == map_state.CONFIDENCE_CAVEAT


def test_rain_driver_gap_follows_the_engine_gate(report, monkeypatch):
    assert isolation_engine.RAIN_DRIVER_VALIDATED is False
    assert "rain_driver" in gaps(report)
    monkeypatch.setattr(isolation_engine, "RAIN_DRIVER_VALIDATED", True)
    assert "rain_driver" not in {g["id"] for g in data_practices.known_gaps(list(flatten_routes(app.routes)))}


def test_response_scan_gap_states_the_name_based_blind_spot(report):
    text = gaps(report)["response_scan"]["text"]
    assert text == RESPONSE_SCAN["limitation"] and "by name" in text and "would not be caught" in text


def test_the_gap_sources_name_real_files():
    for g in data_practices.known_gaps(list(flatten_routes(app.routes))):
        for token in g["source"].split():
            if "/" in token and "." in token.split("/")[-1]:
                assert os.path.exists(ROOT / token.rstrip(")")), f"{g['id']} cites {token}, which doesn't exist"
