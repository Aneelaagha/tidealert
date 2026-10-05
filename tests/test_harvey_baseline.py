"""The Harvey baseline check (scripts/harvey_baseline.py): its masking and diffing, and the committed baseline's
shape. No database."""
import importlib.util
import json
import os

ROOT = os.path.join(os.path.dirname(__file__), "..")
spec = importlib.util.spec_from_file_location("harvey_baseline", os.path.join(ROOT, "scripts", "harvey_baseline.py"))
harvey_baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harvey_baseline)


def test_only_the_listening_demos_random_ids_are_masked():
    text = "late: probe de7323b7 unanswered; check-in 0bde5bc7 answered; USGS-08075770 street block 082db8c3"
    assert harvey_baseline.mask(text) == ("late: probe <id> unanswered; check-in <id> answered; "
                                          "USGS-08075770 street block 082db8c3")


def test_a_changed_confidence_in_the_text_is_reported():
    """This week's incident: Hunting's borrowed HAND agreement moved, and no fingerprint field changed."""
    row = ["isolation", "contradicts", "t", "t", "0.67", 1, "source 0.67 (HAND, borrowed from usgs-08074500 0.64)"]
    moved = row[:4] + ["0.61", 1, "source 0.61 (HAND, borrowed from usgs-03451000 0.50, usgs-08074500 0.64)"]
    diffs = harvey_baseline.diff_contributions({"case": [row]}, {"case": [moved]})
    assert len(diffs) == 1 and "0.61" in diffs[0] and "usgs-03451000" in diffs[0]


def test_missing_and_unexpected_cases_are_reported():
    diffs = harvey_baseline.diff_contributions({"a": [], "b": []}, {"b": [], "c": []})
    assert diffs == ["missing Case: a", "unexpected Case: c"]


def test_the_committed_baseline_is_the_161_cases_and_their_428_contributions():
    base = os.path.join(ROOT, "tests", "baselines", "harvey")
    with open(os.path.join(base, "fingerprints.json")) as f:
        fingerprints = json.load(f)
    with open(os.path.join(base, "contributions.json")) as f:
        contributions = json.load(f)
    assert len(fingerprints) == 161 and len(contributions) == 161
    assert sum(len(v) for v in contributions.values()) == sum(row[6] for row in fingerprints) == 428
