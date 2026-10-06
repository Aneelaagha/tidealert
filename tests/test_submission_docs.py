"""The submission field drafts (docs/submission/fields.md) stay within their limit and keep their shape."""
import re
from pathlib import Path

DOC = (Path(__file__).resolve().parent.parent / "docs" / "submission" / "fields.md").read_text()
FIELDS = ["Disaster Scenario", "Timeliness & Reliability", "Comprehensiveness & Data", "Integration & Responsible Data", "Usability"]


def fields():
    parts = re.split(r"^## (.+)$", DOC, flags=re.M)
    return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts), 2)}


def test_the_five_fields_are_present_in_order():
    assert list(fields()) == FIELDS


def test_each_field_is_under_1200_characters_and_has_exactly_one_next_line():
    for name, text in fields().items():
        assert len(text) < 1200, f"{name}: {len(text)} characters"
        assert len([l for l in text.splitlines() if l.startswith("Next:")]) == 1, name


def test_the_disclosures_are_in_the_text():
    f = fields()
    assert "replay" in f["Disaster Scenario"] and "no real responders" in f["Disaster Scenario"]
    assert "synthetic" in f["Integration & Responsible Data"] and "unvalidated" in f["Timeliness & Reliability"]


def test_the_narration_speaks_both_disclosures_and_names_the_click_path():
    n = (Path(__file__).resolve().parent.parent / "docs" / "submission" / "narration.md").read_text()
    assert "**SAY:** What you're seeing is a replay of Hurricane Harvey" in n and "no real\nresponders" in n
    assert "**SAY:** these responders and their\nassignments are synthetic" in n
    assert "Do not use the copilot" in n and "The exact click path" in n
