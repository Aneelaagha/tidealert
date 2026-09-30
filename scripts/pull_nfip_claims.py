"""Pull NFIP claims from OpenFEMA into the nfip_claims table for given counties and dates.

The isolation pipeline (scripts/run_isolation_pipeline.py) pulls claims for
its basin's counties automatically; this script is for ad-hoc pulls.

Usage (from the repo root):
    .venv/bin/python scripts/pull_nfip_claims.py 48201 48339 48071 --start 2017-08-25 --end 2017-09-02
"""
import argparse
import logging
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.database import SessionLocal  # noqa: E402
from app.services.nfip import pull_claims  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("county_fips", nargs="+", help="5-digit county FIPS codes")
    parser.add_argument("--start", type=date.fromisoformat, required=True, help="first date of loss (inclusive)")
    parser.add_argument("--end", type=date.fromisoformat, required=True, help="last date of loss (inclusive)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    with SessionLocal() as db:
        fetched = pull_claims(db, args.county_fips, args.start, args.end)
    for fips in sorted(args.county_fips):
        print(f"{fips}: {fetched[fips]} claims")
    print(f"Total: {sum(fetched.values())}")


if __name__ == "__main__":
    main()
