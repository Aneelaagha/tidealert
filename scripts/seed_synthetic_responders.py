"""Seed a small set of synthetic responders for one scenario run, so tasks can be assigned in it.

They are not real people: each belongs to the run (responders.run_id), is named
"Synthetic responder N", and has no location (nothing about responder positions
is real yet, and assignment does not use location). Refuses replay and live
runs. Rerunning resets them to available unless they hold an active task.

Usage (from the repo root):
    .venv/bin/python scripts/seed_synthetic_responders.py "replay:2026-09-10T14:00..17:00Z:synthetic:listening"
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Responder, Run, Task  # noqa: E402
from app.models.responder import ResponderStatus  # noqa: E402
from app.models.run import RunMode  # noqa: E402
from app.models.task import ACTIVE_STATUSES  # noqa: E402

# One neutral role: no skills or equipment are modelled, and assignment does not match on them.
ROLE = "synthetic responder (no skills modelled)"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run", help="name of a scenario run")
    parser.add_argument("--count", type=int, default=4)
    args = parser.parse_args()
    with SessionLocal() as db:
        run = db.scalar(select(Run).where(Run.name == args.run))
        if run is None:
            sys.exit(f"no run named {args.run!r}")
        if run.mode != RunMode.scenario:
            sys.exit(f"run {args.run!r} is {run.mode.value}: synthetic responders are only for scenario runs")
        for i in range(1, args.count + 1):
            name = f"Synthetic responder {i}"
            r = db.scalar(select(Responder).where(Responder.run_id == run.id, Responder.name == name))
            if r is None:
                r = Responder(run_id=run.id, name=name)
                db.add(r)
            r.role, r.team_id, r.phone = ROLE, "synthetic", None
            busy = r.id is not None and db.scalar(select(Task.id).where(
                Task.assigned_responder_id == r.id, Task.status.in_(ACTIVE_STATUSES)))
            r.status = ResponderStatus.assigned if busy else ResponderStatus.available
        db.commit()
        for r in db.scalars(select(Responder).where(Responder.run_id == run.id).order_by(Responder.name)):
            print(f"  {r.name}: {r.role}, {r.status.value} (synthetic, no location)")


if __name__ == "__main__":
    main()
