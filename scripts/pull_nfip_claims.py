"""Pull Hurricane Harvey NFIP claims from OpenFEMA into the nfip_claims table.

Source: OpenFEMA "FEMA NFIP Redacted Claims" v3
    https://www.fema.gov/api/open/v3/NfipClaims
    https://www.fema.gov/openfema-data-page/nfip-redacted-claims-v3

No auth is required. The API returns at most 10,000 rows per request, so we
page with $top/$skip, ordered by id so pages are stable.

Each claim's primary key is a UUIDv5 derived from the OpenFEMA record id, so
re-running the script updates rows that are already loaded instead of
duplicating them. Rows missing dateOfLoss or countyCode are skipped and logged.

Note: OpenFEMA redacts claim coordinates to one decimal place (~11 km), so
latitude/longitude are only good for coarse, county-level analysis.

Usage (from the repo root):
    .venv/bin/python scripts/pull_nfip_claims.py
"""
import os
import sys
import time
import uuid
from collections import Counter
from datetime import date

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.dialects.postgresql import insert  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import NfipClaim  # noqa: E402

API_URL = "https://www.fema.gov/api/open/v3/NfipClaims"
PAGE_SIZE = 10_000  # OpenFEMA's maximum $top

COUNTIES = {
    "48201": "Harris",
    "48339": "Montgomery",
    "48071": "Chambers",
}
# Hurricane Harvey window, inclusive of both days.
LOSS_START = "2017-08-25"
LOSS_END = "2017-09-02T23:59:59.999Z"

FIELDS = [
    "id",
    "nfipRatedCommunityNumber",
    "countyCode",
    "censusGeoid",
    "dateOfLoss",
    "ratedFloodZone",
    "amountPaidOnBuildingClaim",
    "amountPaidOnContentsClaim",
    "latitude",
    "longitude",
]

# Stable namespace so the same OpenFEMA record always maps to the same UUID.
OPENFEMA_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, API_URL)


def build_filter() -> str:
    counties = ",".join(f"'{fips}'" for fips in COUNTIES)
    return (
        f"countyCode in ({counties}) "
        f"and dateOfLoss ge '{LOSS_START}' and dateOfLoss le '{LOSS_END}'"
    )


def fetch_page(skip: int, retries: int = 6) -> dict:
    params = {
        "$filter": build_filter(),
        "$select": ",".join(FIELDS),
        "$orderby": "id",
        "$top": PAGE_SIZE,
        "$skip": skip,
        "$count": "true",
    }
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(API_URL, params=params, timeout=180)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            if attempt == retries:
                raise
            print(f"  request failed ({exc}); retrying in {5 * attempt}s")
            time.sleep(5 * attempt)
    raise AssertionError("unreachable")


def to_row(record: dict) -> dict:
    return {
        "id": uuid.uuid5(OPENFEMA_NAMESPACE, str(record["id"])),
        # Community number the policy was rated under at the time of loss.
        "community_id_number": record["nfipRatedCommunityNumber"],
        "county_fips": record["countyCode"],
        "census_geoid": record.get("censusGeoid"),
        "date_of_loss": date.fromisoformat(record["dateOfLoss"][:10]),
        # Flood zone the policy was rated under at the time of loss.
        "flood_zone": record.get("ratedFloodZone"),
        "amount_paid_building": record.get("amountPaidOnBuildingClaim"),
        "amount_paid_contents": record.get("amountPaidOnContentsClaim"),
        "latitude": record.get("latitude"),
        "longitude": record.get("longitude"),
    }


def main() -> None:
    fetched = Counter()
    upserted = 0
    skipped = []
    skip = 0
    total = None

    with SessionLocal() as db:
        while True:
            payload = fetch_page(skip)
            if total is None:
                total = payload["metadata"]["count"]
                print(f"OpenFEMA reports {total} matching claims")

            records = payload["NfipClaims"]
            if not records:
                break

            rows = []
            for record in records:
                if not record.get("dateOfLoss") or not record.get("countyCode"):
                    skipped.append(record.get("id"))
                    print(f"  SKIP OpenFEMA id={record.get('id')}: missing dateOfLoss or countyCode")
                    continue
                rows.append(to_row(record))
            fetched.update(r["county_fips"] for r in rows)

            if rows:
                stmt = insert(NfipClaim).values(rows)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["id"],
                    set_={col: stmt.excluded[col] for col in rows[0] if col != "id"},
                )
                upserted += db.execute(stmt).rowcount
                db.commit()

            skip += len(records)
            print(f"  fetched {skip}/{total}")
            if len(records) < PAGE_SIZE:
                break

        if skip != total:
            print(f"WARNING: fetched {skip} rows but API reported {total}")

        in_db = dict(
            db.execute(
                select(NfipClaim.county_fips, func.count())
                .where(NfipClaim.county_fips.in_(COUNTIES))
                .where(NfipClaim.date_of_loss.between(date(2017, 8, 25), date(2017, 9, 2)))
                .group_by(NfipClaim.county_fips)
            ).all()
        )

    print(f"\nUpserted {upserted} rows; skipped {len(skipped)} with missing dateOfLoss/countyCode\n")
    print(f"{'County':<12}{'FIPS':<8}{'Pulled':>8}{'In DB':>8}")
    for fips, name in COUNTIES.items():
        print(f"{name:<12}{fips:<8}{fetched[fips]:>8}{in_db.get(fips, 0):>8}")
    print(f"{'Total':<20}{sum(fetched.values()):>8}{sum(in_db.values()):>8}")


if __name__ == "__main__":
    main()
