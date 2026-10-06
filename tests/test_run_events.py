"""The event a recorded run replays (app.services.run_events), as /runs reports it."""
def test_recorded_runs_name_their_real_event_and_scenarios_name_none(client, runs):
    by_name = {r["name"]: r for r in runs["all"]}
    assert by_name["backtest:2017-08-25..2017-09-02"]["event"] == "Hurricane Harvey"
    assert runs["listening"]["event"] is None and runs["silence"]["event"] is None  # synthetic: no real event
    if "mixed" in runs:
        assert runs["mixed"]["event"] == "Hurricane Harvey"
    helene = by_name.get("backtest:2024-09-25..2024-09-30")
    if helene:
        assert helene["event"] == "Hurricane Helene"


def test_the_recorded_peak_is_the_first_tick_where_every_flagged_zone_is_cut_off(client, runs):
    """peak_at is written in app.services.run_events, so it is pinned to the stored evidence: at that tick every zone
    the run ever flags is cut off at once, and half an hour earlier some are not (a count can't exceed the number of
    flagged zones, so it is a maximum)."""
    from datetime import datetime, timedelta
    harvey = runs["harvey"]
    peak = datetime.fromisoformat(harvey["peak_at"])
    assert peak.isoformat() == "2017-08-27T20:00:00+00:00"
    flagged = {c["zone_id"] for c in client.get("/cases", params={"run_id": harvey["id"]}).json()["cases"]}
    def cut_off(at):
        d = client.get("/map/supply-access", params={"run_id": harvey["id"], "at": at.isoformat()}).json()
        return d["counts"]["isolated"]["zones"]
    assert cut_off(peak) == len(flagged) == 152
    assert cut_off(peak - timedelta(minutes=30)) < len(flagged)


def test_runs_without_a_recorded_peak_say_so(client, runs):
    assert runs["listening"]["peak_at"] is None and runs["silence"]["peak_at"] is None
