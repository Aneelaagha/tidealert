"""Check (or write) the Harvey baseline: the Cases the check bar requires to stay identical.

Two layers, both compared against files committed in tests/baselines/harvey/:

1. fingerprints.json: the 161 non-mixed Case fingerprints (source, zone, opened_at, household, confidence word,
   status, contribution count). Unchanged from the check bar's original list.
2. contributions.json: every contribution of those Cases, in full: engine, direction, first and latest observation
   time, engine confidence and rule text. The fingerprints can't see a change in what a contribution SAYS or how
   confident it is (e.g. Hunting Bayou's borrowed HAND agreement moving from 0.67 to 0.62 changes no count); this
   layer can.

Only Cases from the baseline's own sources are compared, so other runs (the mixed run, Helene, future regions) don't
affect the check; a new Case or a missing one in a baseline source does. The listening demo gives its probes and
check-ins random ids on every rebuild; those ids are masked, nothing else is.

Run after the Harvey replay, the silence sweep and scripts/listening_demo.py:
    python scripts/harvey_baseline.py            # check; exit 1 on any difference
    python scripts/harvey_baseline.py --write    # rewrite the baseline (only with the owner's approval)
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import func, select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Case, Zone  # noqa: E402
from app.models.case_engine_contribution import CaseEngineContribution  # noqa: E402

BASELINE_DIR = os.path.join(os.path.dirname(__file__), "..", "tests", "baselines", "harvey")
RANDOM_IDS = re.compile(r"\b(probe|check-in) [0-9a-f]{8}\b")


def mask(text: str) -> str:
    return RANDOM_IDS.sub(r"\1 <id>", text)


def case_key(case: Case, zone_name: str) -> str:
    return " | ".join([case.source or "", zone_name, case.opened_at.isoformat(), str(case.household_id or "")])


def snapshot(db, sources: set[str]) -> tuple[list, dict]:
    """(fingerprints, contributions) for every Case whose source is in `sources`."""
    counts = dict(db.execute(select(CaseEngineContribution.case_id, func.count())
                             .group_by(CaseEngineContribution.case_id)).all())
    fingerprints, contributions = [], {}
    for case, zone_name in db.execute(select(Case, Zone.name).join(Zone, Zone.id == Case.zone_id)
                                      .where(Case.source.in_(sources))):
        fingerprints.append([case.source or "", zone_name, case.opened_at.isoformat(), str(case.household_id or ""),
                             case.confidence_word.value, case.status.value, counts.get(case.id, 0)])
        contributions[case_key(case, zone_name)] = sorted(
            [c.engine.value, c.direction.value, c.first_observed_at.isoformat(), c.observed_at.isoformat(),
             repr(c.engine_confidence), c.independent_sources, mask(c.rule_fragment)]
            for c in case.contributions)
    return sorted(fingerprints), dict(sorted(contributions.items()))


def diff_contributions(expected: dict, actual: dict, limit: int = 5) -> list[str]:
    """Human-readable differences, at most `limit` of them."""
    out = []
    for key in sorted(set(expected) | set(actual)):
        if key not in actual:
            out.append(f"missing Case: {key}")
        elif key not in expected:
            out.append(f"unexpected Case: {key}")
        elif expected[key] != actual[key]:
            for e, a in zip(expected[key] + [None] * len(actual[key]), actual[key] + [None] * len(expected[key])):
                if e != a:
                    out.append(f"{key}\n    expected: {e}\n    actual:   {a}")
                    break
        if len(out) >= limit:
            break
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true", help="rewrite the baseline from the database")
    args = parser.parse_args()
    fp_path = os.path.join(BASELINE_DIR, "fingerprints.json")
    ct_path = os.path.join(BASELINE_DIR, "contributions.json")
    with open(fp_path) as f:
        expected_fp = json.load(f)
    sources = {row[0] for row in expected_fp}
    with SessionLocal() as db:
        fingerprints, contributions = snapshot(db, sources)

    if args.write:
        with open(fp_path, "w") as f:
            json.dump(fingerprints, f, indent=0)
        with open(ct_path, "w") as f:
            json.dump(contributions, f, indent=1)
        print(f"wrote {len(fingerprints)} fingerprints, {sum(map(len, contributions.values()))} contributions")
        return 0

    with open(ct_path) as f:
        expected_ct = json.load(f)
    fp_ok = fingerprints == expected_fp
    ct_ok = contributions == expected_ct
    n = sum(map(len, contributions.values()))
    print(f"fingerprints:  {len(fingerprints)} Cases, {'IDENTICAL' if fp_ok else 'DIFFER'} "
          f"(baseline {len(expected_fp)})")
    print(f"contributions: {n} in {len(contributions)} Cases (text, confidence, times), "
          f"{'IDENTICAL' if ct_ok else 'DIFFER'} (baseline {sum(map(len, expected_ct.values()))})")
    if not fp_ok:
        for row in [r for r in expected_fp if r not in fingerprints][:5]:
            print(f"  fingerprint missing or changed: {row}")
    for line in diff_contributions(expected_ct, contributions):
        print(f"  {line}")
    return 0 if fp_ok and ct_ok else 1


if __name__ == "__main__":
    sys.exit(main())
