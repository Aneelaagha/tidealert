"""A step with no data stays missing (app.services.stage "missing"), all the way through. Synthetic gaps only; no
Helene data is read. The Harvey checks read the local database (read-only) and skip without it."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pytest
from app.services import case_matcher, stage
from app.services.river_driver import depth_over_channel, library_level
from app.services.stage import MAX_RATING_GAP, RatingCurve, observed_stage

T0 = datetime(2030, 1, 1, tzinfo=timezone.utc)
STEP = timedelta(minutes=15)


def ts(*minutes):
    return np.array([(T0 + timedelta(minutes=m)).timestamp() for m in minutes])


def series(monkeypatch, gage, discharge):
    """observed_stage against synthetic gage height and discharge: lists of (minute, value)."""
    def fake(db, source, variable, measured_only=False):
        pts = gage if variable == "gage_height_ft" else discharge
        return ts(*[m for m, _ in pts]), np.array([v for _, v in pts], dtype=float)
    monkeypatch.setattr(stage, "_series", fake)


RATING = RatingCurve(log_q=np.log(np.array([100.0, 1000.0])), stage_ft=np.array([2.0, 10.0]))


def provenance(monkeypatch, gage, discharge, minutes):
    series(monkeypatch, gage, discharge)
    s = observed_stage(None, "x", [T0 + timedelta(minutes=m) for m in minutes], RATING)
    return s.provenance, s.stage_ft


def test_the_cap_is_three_hours_and_documented_as_coming_from_harvey():
    assert MAX_RATING_GAP == timedelta(hours=3)
    assert "150 min" in stage.__doc__ and "not a physical constant" in stage.__doc__


def test_gage_height_is_used_within_thirty_minutes(monkeypatch):
    prov, h = provenance(monkeypatch, [(0, 5.0), (30, 6.0)], [], [0, 15, 30])
    assert prov == ["observed"] * 3 and h[1] == pytest.approx(5.5)


def test_discharge_fills_a_gage_gap_only_between_readings_at_most_three_hours_apart(monkeypatch):
    gage = [(0, 5.0)]  # gage height stops after minute 0
    discharge = [(0, 300.0), (180, 300.0), (420, 300.0)]  # 3 h apart, then 4 h apart
    prov, h = provenance(monkeypatch, gage, discharge, [60, 120, 240, 360])
    assert prov == ["rating", "rating", "missing", "missing"]
    assert np.isfinite(h[:2]).all() and np.isnan(h[2:]).all()


def test_nothing_is_extrapolated_past_the_discharge_record(monkeypatch):
    prov, _ = provenance(monkeypatch, [(0, 5.0)], [(0, 300.0), (60, 300.0)], [120, 240])
    assert prov == ["missing", "missing"]  # np.interp would have held the last value flat


def test_a_crossing_after_a_missing_step_is_only_known_to_that_step():
    s = stage.StageSeries(times=[T0, T0 + STEP, T0 + 2 * STEP], stage_ft=np.array([5.0, np.nan, 12.0]),
                          provenance=["observed", "missing", "observed"])
    assert s.first_crossing(10.0) == T0 + 2 * STEP
    assert list(s.missing) == [False, True, False]


def test_a_missing_step_never_selects_the_top_flood_map_layer():
    stages = np.array([20.0, 22.0, 24.0])
    level = library_level(stages, np.array([19.0, 21.0, np.nan, 30.0]))
    assert level[0] == -np.inf and level[1] == 22.0 and level[3] == 24.0
    assert np.isnan(level[2])  # before the fix: 24.0, the largest mapped flood


def test_the_hand_fallback_depth_survives_a_missing_step():
    site = SimpleNamespace(site_id="x", gauge_vertical_datum="NGVD29", stage_to_wse_m=lambda s: None)
    s = stage.StageSeries(times=[T0] * 3, stage_ft=np.array([4.0, np.nan, 6.0]), provenance=["observed", "missing",
                                                                                           "observed"])
    depth, method = depth_over_channel(site, s, terrain=None)
    assert "FALLBACK" in method and depth[0] == 0.0 and np.isnan(depth[1]) and depth[2] > 0


def test_the_case_matcher_records_nothing_at_a_missing_step():
    """A NaN level reads as 'every road dry': without the guard every tracked Case would be reconnected."""
    sweeper = object.__new__(case_matcher.CaseSweeper)
    sweeper.ctx = SimpleNamespace(times=[T0], river=SimpleNamespace(level=np.array([np.nan])))
    sweeper._zone_cases = {"z": SimpleNamespace(state="stranded")}

    def must_not_contribute(*a, **k):
        raise AssertionError("no evidence may be recorded at a missing step")
    sweeper._contribute = must_not_contribute
    result = case_matcher.SweepResult(T0)
    sweeper._isolation(T0, result)
    assert result.missing_steps == 1 and result.contributions == 0
    assert sweeper._zone_cases["z"].state == "stranded"  # not reconnected


# ---------------------------------------------------------------- Harvey is unchanged
@pytest.mark.parametrize("site", ["08074500", "08076000", "08075770"])
def test_harvey_has_no_missing_steps(site, runs):
    from app.database import SessionLocal
    from app.services.river_driver import HARVEY_END, HARVEY_START
    with SessionLocal() as db:
        s = observed_stage(db, site, stage.timesteps(HARVEY_START, HARVEY_END, STEP), stage.fit_event_rating(db, site))
    assert "missing" not in s.provenance and np.isfinite(s.stage_ft).all()
    assert s.provenance.count("rating") == {"08074500": 426, "08076000": 2, "08075770": 220}[site]
