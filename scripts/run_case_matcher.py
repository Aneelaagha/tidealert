"""Run the case matcher: a sweep every 15 minutes that opens and updates Cases.

Replay mode (the only mode for now) steps a clock through a past event
window. There is no live registry or probe cascade yet, so --live exits with
an explanation.

Gauge replays need scripts/run_isolation_pipeline.py to have run for each
gauge first (they load its caches and zones). Replay cases are labelled
backtest:<window>:USGS-<site> and replace that label's previous cases.

A silence-only replay (--silence-region) sweeps the households of one zone
region over a window, e.g. the synthetic test households:

    .venv/bin/python scripts/run_case_matcher.py --silence-region synthetic:silence-baseline \\
        --start 2026-09-02T14:00Z --end 2026-09-02T19:00Z

Usage (from the repo root):
    .venv/bin/python scripts/run_case_matcher.py 08074500 08076000 08075770
"""
import argparse
import asyncio
import logging
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Zone  # noqa: E402
from app.services.case_matcher import (  # noqa: E402
    CADENCE, CaseSweeper, LiveClock, ReplayClock, replay_source, run_scheduler,
)
from app.services.river_driver import HARVEY_END, HARVEY_START, load_site_context  # noqa: E402
from app.services.stage import timesteps  # noqa: E402


def utc_arg(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sites", nargs="*", help="USGS site numbers to replay")
    parser.add_argument("--start", type=utc_arg, default=HARVEY_START)
    parser.add_argument("--end", type=utc_arg, default=HARVEY_END)
    parser.add_argument("--cadence-minutes", type=int, default=int(CADENCE.total_seconds() // 60))
    parser.add_argument("--silence-region", help="sweep only the households of this zone region")
    parser.add_argument("--live", action="store_true", help="live sweeps (not available yet)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    if args.live:
        try:
            LiveClock().__aiter__()
        except NotImplementedError as exc:
            sys.exit(f"--live: {exc}")

    step = timedelta(minutes=args.cadence_minutes)
    ticks = timesteps(args.start, args.end, step)
    totals: dict[str, Counter] = {}

    def on_sweep(source, result):
        c = totals.setdefault(source, Counter())
        c["sweeps"] += 1
        c["opened"] += result.opened
        c["contributions"] += result.contributions

    with SessionLocal() as db:
        # Sweeps commit every tick; keep tracked cases loaded instead of re-reading them after each commit.
        db.expire_on_commit = False
        sweepers = []
        for site_id in args.sites:
            ctx = load_site_context(db, site_id, args.start, args.end, step)
            if ctx.times != ticks:
                sys.exit(f"USGS {site_id}: context timesteps do not match the replay ticks")
            sweepers.append(CaseSweeper(db=db, source=replay_source(args.start, args.end, ctx.tz,
                                                                    f"USGS-{site_id}"), tz=ctx.tz, ctx=ctx))
        if args.silence_region:
            zone_ids = list(db.scalars(select(Zone.id).where(Zone.region == args.silence_region)))
            sweepers.append(CaseSweeper(db=db, source=replay_source(args.start, args.end, timezone.utc,
                                                                    args.silence_region),
                                        tz=timezone.utc, household_zone_ids=zone_ids))
        if not sweepers:
            parser.error("give at least one site or --silence-region")

        started = datetime.now()
        asyncio.run(run_scheduler(ReplayClock(ticks), sweepers, on_sweep))
        elapsed = (datetime.now() - started).total_seconds()

    print(f"Replayed {len(ticks)} sweeps every {args.cadence_minutes} min, {args.start:%Y-%m-%d %H:%M} .. "
          f"{args.end:%Y-%m-%d %H:%M} UTC, in {elapsed:.0f} s")
    for source, c in totals.items():
        print(f"  {source}: {c['opened']} cases opened, {c['contributions']} contributions over {c['sweeps']} sweeps")


if __name__ == "__main__":
    main()
