import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    return TestClient(app)


@pytest.fixture(scope="session")
def runs(client):
    """Runs in the local database, by kind. The tests read (never write) the database: run the Harvey replay
    (scripts/run_case_matcher.py 08074500 08076000 08075770), scripts/silence_baseline_demo.py plus its silence
    sweep, and scripts/listening_demo.py first. The mixed run (scripts/mixed_harvey_scenario.py) is optional; tests that
    need it skip without it."""
    body = client.get("/runs").json()
    by = {}
    for run in body["runs"]:
        if run["mode"] == "replay" and run["name"] == "backtest:2017-08-25..2017-09-02":
            by["harvey"] = run
        elif run["name"].endswith("synthetic:listening"):
            by["listening"] = run
        elif run["name"].endswith("synthetic:silence-baseline"):
            by["silence"] = run
        elif run["name"] == "mixed:harvey-synthetic-responders:2017-08-25..2017-09-02":
            by["mixed"] = run  # optional: scripts/mixed_harvey_scenario.py; tests that need it skip without it
    missing = {"harvey", "listening", "silence"} - set(by)
    if missing:
        pytest.skip(f"runs not in the local database: {sorted(missing)}")
    by["vocabulary"] = body["vocabulary"]
    by["all"] = body["runs"]
    return by
