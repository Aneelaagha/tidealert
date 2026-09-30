"""Demonstrate the silence engine's per-household baseline on the synthetic probe data.

Run scripts/generate_synthetic_probes.py first. All data here is synthetic
(generated from log-normal response habits), so this checks that the
statistics behave as intended, not that they are right for real households.

1. Stores each synthetic household's baseline (median, variance, probe count).
2. Writes two new probes, both answered after 30 minutes: one from the fast
   responder (median ~90 s) and one from the slow responder (median ~40 min),
   plus a fast-responder probe still unanswered after 10 minutes. Each is
   judged against that household's baseline from earlier probes only.
3. Held-out check across all synthetic households: baseline from each
   household's first 30 probes, then its remaining answered probes (normal)
   and injected late responses (3x and 10x its own median), judged by the
   personal baseline vs one threshold for everyone (the 99th percentile of
   all households' training latencies: "slower than 99% of responses seen").

Usage (from the repo root):
    .venv/bin/python scripts/silence_baseline_demo.py
"""
import math
import os
import sys
import uuid
from datetime import timedelta

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import delete, select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Household, ProbeResponse  # noqa: E402
from app.models.probe_response import ProbeChannel  # noqa: E402
from app.services import silence_baseline as sb  # noqa: E402
from generate_synthetic_probes import (  # noqa: E402
    FAST, HISTORY_END, N_HOUSEHOLDS, NAMESPACE, SLOW, household_id,
)

TRAIN = 30
LATE_FACTORS = (3.0, 10.0)
ONE_SIZE_PERCENTILE = 99


def fmt_s(seconds: float) -> str:
    return f"{seconds:6.0f} s" if seconds < 120 else f"{seconds / 60:6.1f} min"


def main() -> None:
    fast_id, slow_id = household_id(0), household_id(1)
    with SessionLocal() as db:
        ids = [household_id(i) for i in range(N_HOUSEHOLDS)]
        demo_ids = [uuid.uuid5(NAMESPACE, f"demo-{k}") for k in range(3)]
        db.execute(delete(ProbeResponse).where(ProbeResponse.id.in_(demo_ids)))
        db.commit()

        # 1. Stored baselines.
        sb.update_household_baselines(db, ids)
        print("1. Stored baselines (synthetic households)")
        for hid, label in ((fast_id, FAST.label), (slow_id, SLOW.label)):
            h = db.get(Household, hid)
            b = sb.household_baseline(db, hid)
            print(f"   {str(hid)[:8]} {label:32s} probes {h.probe_count:3d} (baseline window: last {b.answered} "
                  f"answered)  median "
                  f"{fmt_s(h.median_response_seconds)}  sd {fmt_s(math.sqrt(h.response_variance_seconds))}  "
                  f"late after {fmt_s(b.late_after_seconds)}")

        # 2. New probes, judged against each household's own earlier history.
        sent = HISTORY_END + timedelta(days=1, hours=14)
        scenario = [
            (demo_ids[0], fast_id, FAST.label, sent, sent + timedelta(minutes=30)),
            (demo_ids[1], slow_id, SLOW.label, sent, sent + timedelta(minutes=30)),
            (demo_ids[2], fast_id, FAST.label, sent + timedelta(hours=3), None),  # still silent
        ]
        for pid, hid, _, sent_at, responded_at in scenario:
            db.add(ProbeResponse(id=pid, household_id=hid, channel=ProbeChannel.sms, sent_at=sent_at,
                                 responded_at=responded_at, response_code="OK" if responded_at else None))
        db.commit()
        print("\n2. New probes (written as ProbeResponse rows), each judged against the household's earlier probes")
        for pid, hid, label, sent_at, responded_at in scenario:
            probe = db.get(ProbeResponse, pid)
            baseline = sb.household_baseline(db, hid, before=probe.sent_at)
            elapsed = ((responded_at or sent_at + timedelta(minutes=10)) - sent_at).total_seconds()
            v = sb.evaluate(baseline, elapsed)
            what = f"answered after {fmt_s(elapsed)}" if responded_at else f"silent for {fmt_s(elapsed)} so far"
            print(f"   {label:32s} {what:30s} -> {v.status.upper():6s} (z {v.z:+.1f}; late after "
                  f"{fmt_s(v.late_after_seconds)} for this household)")

        # 3. Held-out comparison: personal baseline vs one threshold for everyone.
        train, train_lat, test_normal, test_late = {}, {}, {}, {}
        for hid in ids:
            rows = db.execute(select(ProbeResponse.sent_at, ProbeResponse.responded_at)
                              .where(ProbeResponse.household_id == hid, ProbeResponse.id.not_in(demo_ids))
                              .order_by(ProbeResponse.sent_at)).all()
            lat = [(r.responded_at - r.sent_at).total_seconds() if r.responded_at else None for r in rows]
            train_lat[hid] = [x for x in lat[:TRAIN] if x is not None]
            train[hid] = sb.compute_baseline(hid, train_lat[hid], probe_count=TRAIN)
            test_normal[hid] = [x for x in lat[TRAIN:] if x is not None]
            test_late[hid] = {f: f * train[hid].median_seconds for f in LATE_FACTORS}
        # One size for everyone: slower than 99% of all training responses, across all households.
        global_late_after = float(np.percentile([x for hid in ids for x in train_lat[hid]], ONE_SIZE_PERCENTILE))

        def personal(hid, x):
            return sb.evaluate(train[hid], x).status == "late"

        def everyone(x):
            return x > global_late_after

        n_normal = sum(len(v) for v in test_normal.values())
        fp_personal = [h for h in ids for x in test_normal[h] if personal(h, x)]
        fp_global = [h for h in ids for x in test_normal[h] if everyone(x)]
        slow = {h for h in ids if train[h].median_seconds >= 600}
        print(f"\n3. Held-out check on {N_HOUSEHOLDS} synthetic households (baseline from first {TRAIN} probes; "
              f"one-size rule = late after {fmt_s(global_late_after)}, the p{ONE_SIZE_PERCENTILE} of all training "
              f"responses)")
        print(f"   normal responses flagged late (false positives): personal {len(fp_personal)}/{n_normal} "
              f"({len(fp_personal) / n_normal:.1%})   one-size {len(fp_global)}/{n_normal} "
              f"({len(fp_global) / n_normal:.1%}, {sum(h in slow for h in fp_global)} of them from the "
              f"{len(slow)} households with a median >= 10 min)")
        for f in LATE_FACTORS:
            hp = [h for h in ids if personal(h, test_late[h][f])]
            hg = [h for h in ids if everyone(test_late[h][f])]
            print(f"   injected late responses ({f:.0f}x own median) caught: personal {len(hp)}/{N_HOUSEHOLDS}   "
                  f"one-size {len(hg)}/{N_HOUSEHOLDS} (fast households caught: personal "
                  f"{sum(h not in slow for h in hp)}/{N_HOUSEHOLDS - len(slow)}, one-size "
                  f"{sum(h not in slow for h in hg)}/{N_HOUSEHOLDS - len(slow)})")

if __name__ == "__main__":
    main()
