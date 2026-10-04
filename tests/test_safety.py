"""Zone-based responder safety (app.services.safety) against the local database (read-only) and as pure logic.
Harvey has a real flood timeline but no responders; the scenarios have synthetic responders but no isolation engine.
The after-assignment warning can't occur in either yet, so it is tested on its logic here."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Case, Run, Zone
from app.services import safety

H_PEAK = "2017-08-27T18:30:00Z"
T = datetime(2017, 8, 27, 4, 0, tzinfo=timezone.utc)


def tasks(client, run, at=None):
    params = {"run_id": run["id"]} | ({"at": at} if at else {})
    return client.get("/tasks", params=params).json()["tasks"]


# ---------------------------------------------------------------- Harvey: real timeline, nobody assigned
def test_harvey_at_the_peak_warns_on_every_cut_off_task_and_says_nobody_is_assigned(client, runs):
    active = [t for t in tasks(client, runs["harvey"], H_PEAK) if t["active"]]
    assert active and all(t["safety"]["zone_access"] == "isolated" for t in active)
    for t in active:
        (w,) = t["safety"]["warnings"]
        assert w["code"] == "zone_isolated" and "No responder is assigned" in w["text"]
        assert t["safety"]["mechanism"] in ("stranded", "submerged")
        assert t["safety"]["assignment_note"] == safety.NO_ASSIGNMENT  # stated, not silent


def test_harvey_reconnected_zones_are_not_called_reachable(client, runs):
    later = [t for t in tasks(client, runs["harvey"], "2017-08-30T12:00:00Z") if t["active"]]
    assert later and all(t["safety"]["zone_access"] == "reconnected" for t in later)
    assert all(not t["safety"]["warnings"] and "reconnected" in t["safety"]["reason"] for t in later)


def test_harvey_isolation_matches_each_cases_own_latest_evidence(client, runs):
    """The task's zone access agrees with the Case evidence the zone panel shows."""
    at = "2017-08-28T20:00:00Z"
    cases = client.get("/cases", params={"run_id": runs["harvey"]["id"], "at": at}).json()["cases"]
    states = set()
    for c in cases:
        iso = [x for x in c["contributions"] if x["engine"] == "isolation" and x["direction"] in ("supports", "contradicts")]
        latest = max(iso, key=lambda x: x["first_observed_at"])["direction"]
        for t in c["tasks"]:
            want = "isolated" if latest == "supports" else "reconnected"
            assert t["safety"]["zone_access"] == want, (c["id"], t["safety"]["zone_access"])
            states.add(want)
    assert states == {"isolated", "reconnected"}  # this time has both


def test_cases_and_tasks_report_the_same_safety(client, runs):
    by_task = {t["id"]: t["safety"] for t in tasks(client, runs["harvey"], H_PEAK)}
    cases = client.get("/cases", params={"run_id": runs["harvey"]["id"], "at": H_PEAK}).json()["cases"]
    for c in cases:
        for t in c["tasks"]:
            assert t["safety"] == by_task[t["id"]]


def test_zones_without_tasks_read_reachable_or_not_evaluated_never_safe_by_default(runs):
    with SessionLocal() as db:
        run = db.get(Run, runs["harvey"]["id"])
        at = datetime(2017, 8, 27, 18, 30, tzinfo=timezone.utc)
        never_isolated = select(Case.zone_id).where(Case.run_id == run.id)
        gapless = db.scalar(select(Zone.id).where(Zone.region == "USGS-08074500 basin", Zone.coverage_gaps.is_(None),
                                                  Zone.id.not_in(never_isolated)))
        cut_at_base = next(z.id for z in db.scalars(select(Zone).where(Zone.region.like("USGS-%")))
                           if isinstance((z.coverage_gaps or {}).get("isolation"), str))
        access = safety.zone_access(db, run, at, [gapless, cut_at_base])
    assert access[str(gapless)]["zone_access"] == "reachable"  # evaluated, no gap, never isolated
    assert access[str(cut_at_base)]["zone_access"] == "not_evaluated"


# ---------------------------------------------------------------- scenarios: synthetic zones, never assessed
def test_scenarios_say_isolation_is_not_assessed_and_never_warn(client, runs):
    for kind in ("listening", "silence"):
        ts = tasks(client, runs[kind])
        assert ts
        for t in ts:
            assert t["safety"]["zone_access"] == "not_evaluated" and t["safety"]["reason"] == safety.NOT_RUN_REASON
            assert t["safety"]["warnings"] == []


# ---------------------------------------------------------------- the warning logic
def state(events, active=True):
    last = events[-1]
    return {"active": active, "assigned_responder_id": last[1], "events": [{"at": a, "assigned_responder_id": r} for a, r in events]}


ISOLATED = {"zone_access": "isolated", "since": T, "mechanism": "stranded", "reason": "…"}


def test_cut_off_after_assignment():
    s = state([(T - timedelta(hours=2), None), (T - timedelta(hours=1), "r1")])
    (w,), note = safety.warnings_for(s, ISOLATED)
    assert w["code"] == "isolated_after_assignment" and "after the responder was assigned" in w["text"] and note is None


def test_assigned_into_an_already_cut_off_zone():
    s = state([(T - timedelta(hours=2), None), (T + timedelta(hours=1), "r1")])
    (w,), _ = safety.warnings_for(s, ISOLATED)
    assert w["code"] == "zone_isolated" and "assigned after that" in w["text"]


def test_reassignment_uses_the_current_assignees_start():
    s = state([(T - timedelta(hours=3), "r1"), (T - timedelta(hours=2), None), (T + timedelta(hours=1), "r2")])
    (w,), _ = safety.warnings_for(s, ISOLATED)
    assert w["code"] == "zone_isolated"  # r2 came after the isolation, even though r1 was there before


def test_possibly_isolated_is_a_lower_severity_warning_and_closed_tasks_never_warn():
    possibly = {"zone_access": "possibly_isolated", "since": T, "mechanism": None, "reason": "…"}
    (w,), note = safety.warnings_for(state([(T, None)]), possibly)
    assert (w["code"], w["severity"], note) == ("zone_possibly_isolated", "medium", safety.NO_ASSIGNMENT)
    assert safety.warnings_for(state([(T, "r1")], active=False), ISOLATED) == ([], None)


def test_not_evaluated_and_reconnected_give_no_warning():
    for kind in ("not_evaluated", "reconnected", "reachable"):
        assert safety.warnings_for(state([(T, None)]), {**ISOLATED, "zone_access": kind}) == ([], None)
