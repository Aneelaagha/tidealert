"""HAND's borrowed source agreement comes only from the declared gauges (isolation_cases.HAND_PRIOR_GAUGES), so a new
region's pipeline report can't change Harvey's numbers. No database: reports are written to a temp data dir."""
import json

import pytest

from app.services import isolation_cases


def write(data_dir, site, median):
    d = data_dir / f"usgs-{site}"
    d.mkdir()
    (d / "backtest.json").write_text(json.dumps({"hand_vs_nws_iou": {"event_steps_median": median}}))


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(isolation_cases, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(isolation_cases, "_hand_prior", None)
    return tmp_path


def test_the_sources_are_declared_harveys_two_library_gauges():
    assert isolation_cases.HAND_PRIOR_GAUGES == ("08074500", "08076000")


def test_another_gauges_report_is_ignored(data_dir):
    write(data_dir, "08074500", 0.64)
    write(data_dir, "08076000", 0.70)
    write(data_dir, "03451000", 0.50)  # e.g. a new region with a usable library
    value, note = isolation_cases.hand_agreement_prior()
    assert value == pytest.approx(0.67)
    assert note == "borrowed from usgs-08074500 0.64, usgs-08076000 0.70"


def test_a_missing_declared_gauge_is_a_named_fallback_not_a_partial_mean(data_dir):
    write(data_dir, "08074500", 0.64)
    write(data_dir, "03451000", 0.50)
    value, note = isolation_cases.hand_agreement_prior()
    assert value == 0.5 and note.startswith("FALLBACK 0.5") and "08076000" in note
