"""Pull NFIP claims from OpenFEMA ("FEMA NFIP Redacted Claims" v3) into nfip_claims.

    https://www.fema.gov/api/open/v3/NfipClaims
    https://www.fema.gov/openfema-data-page/nfip-redacted-claims-v3

No auth is required. The API returns at most 10,000 rows per request, so we
page with $top/$skip, ordered by id so pages are stable. Each claim's primary
key is a UUIDv5 of its OpenFEMA id, so re-runs update rows in place. Rows
missing dateOfLoss or countyCode are skipped and logged.

OpenFEMA redacts coordinates to one decimal place (~11 km); censusGeoid (the
12-digit census block group) is the usable location. Its vintage is mixed:
some claims carry 2010 block group GEOIDs and some 2020.
"""
import logging
import time
import uuid
from collections import Counter
from datetime import date

import requests
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import NfipClaim

log = logging.getLogger(__name__)

API_URL = "https://www.fema.gov/api/open/v3/NfipClaims"
PAGE_SIZE = 10_000  # OpenFEMA's maximum $top
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


def _fetch_page(filter_: str, skip: int, retries: int = 6) -> dict:
    params = {
        "$filter": filter_,
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
            log.warning("OpenFEMA request failed (%s); retrying in %ss", exc, 5 * attempt)
            time.sleep(5 * attempt)
    raise AssertionError("unreachable")


def _to_row(record: dict) -> dict:
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


def pull_claims(db: Session, county_fips: list[str], start: date, end: date) -> Counter:
    """Upsert all claims for these counties with date of loss in [start, end]; return rows per county."""
    counties = ",".join(f"'{fips}'" for fips in sorted(county_fips))
    filter_ = (
        f"countyCode in ({counties}) "
        f"and dateOfLoss ge '{start.isoformat()}' and dateOfLoss le '{end.isoformat()}T23:59:59.999Z'"
    )
    fetched = Counter()
    skipped = 0
    skip = 0
    total = None
    while True:
        payload = _fetch_page(filter_, skip)
        if total is None:
            total = payload["metadata"]["count"]
            log.info("OpenFEMA reports %d claims for counties %s", total, counties)
        records = payload["NfipClaims"]
        if not records:
            break

        rows = []
        for record in records:
            if not record.get("dateOfLoss") or not record.get("countyCode"):
                skipped += 1
                log.warning("SKIP OpenFEMA id=%s: missing dateOfLoss or countyCode", record.get("id"))
                continue
            rows.append(_to_row(record))
        fetched.update(r["county_fips"] for r in rows)
        if rows:
            stmt = insert(NfipClaim).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["id"],
                set_={col: stmt.excluded[col] for col in rows[0] if col != "id"},
            )
            db.execute(stmt)
            db.commit()

        skip += len(records)
        if len(records) < PAGE_SIZE:
            break
    if skip != total:
        log.warning("OpenFEMA: fetched %d rows but API reported %d", skip, total)
    if skipped:
        log.warning("Skipped %d claims with missing dateOfLoss/countyCode", skipped)
    return fetched
