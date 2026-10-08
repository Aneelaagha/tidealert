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
